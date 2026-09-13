"""`admit()`: steps 4-6 of 05:2519's ladder, and the three-valued verdict.

The load-bearing test is `test_the_worked_page_admission_reserves_the_four_dimensions_it_names`,
which is `02:563`'s own trace executed against a real ledger: a `PAGE` decision reserving `micros`,
`tokens_out`, `calls` and `gpu_ms` against `[budget.per_part]`'s four numbers, with the p95 multiple
applied to exactly the two output-proportional dimensions.

Two things are transcriptions rather than inventions:

* `[budget.per_part]` and `[budget.per_unit]`'s numbers are read out of `05`'s own TOML fence, so
  the worked example is the plan's arithmetic and not a copy of it.
* `route_decision.admission`'s CHECK values are read out of `0004_runtime.sql` and compared against
  `ADMISSIONS`' three, in both directions.

## The test that is a defect report

`test_the_first_exhausted_dimension_is_the_plans_first_and_the_plan_does_not_say_which` shows that
`05:2506`'s "first exhausted dimension wins" fixes an outcome and not an order, and that the order
`requests()` emits -- `DIMS`, which is `Spend`'s -- is the only one under which two runs over one
corpus report the same bound dimension. **D174.**
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, Any

import omniweave_core.store.sqlite as ow
import pytest
from omniweave_core.budget import (
    ADMISSIONS,
    DIMS,
    INPUT_PROPORTIONAL,
    OUTPUT_PROPORTIONAL,
    PER_UNIT_MICROS_KEYS,
    UNCAPPED,
    Admitted,
    Deferred,
    Degraded,
    admission_of,
    admit,
    per_unit_micros,
    requests,
    reservation_id,
    writes_exhausted,
)
from omniweave_core.observe.degradation import Degradation
from omniweave_core.store import migrate
from omniweave_core.store.budget import SqliteBudgetLedger

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from conftest import PlanDocs


P95 = 3.2
"""`05:2454`'s `tokens_out_p95_multiple`. `ow drivers check` FAILS if this is understated."""


_SEED = (
    "INSERT INTO run(run_id, generation, trigger, argv, config_digest, semantic_digest,"
    " policy_digest, pricebook_digest, lock_digest, omniweave_version, contract, schema,"
    " started_ns, status, manifest_path)"
    " VALUES('r_1', 1, 'cli', '[]', 'c', 's', 'p', 'pb', 'l', '0.1', 1, 1, 1, 'running', 'm')",
    "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen)"
    " VALUES('c:/x/a.pdf', 'planned', 'internal', 1)",
    "INSERT INTO route_evidence(evidence_digest, payload, first_seen_at) VALUES('ev', X'00', 1)",
    "INSERT INTO route_decision(decision_id, content_sha256, unit_part, lane, rung,"
    " policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class,"
    " rule_id, rule_origin, slice_key, evidence_digest, est_spend, est_micros, reserved_micros,"
    " admission, generation, decided_at)"
    " VALUES('d_1', 'c0', 'p1', 'parse', 1, 'pd', 'pb', 'hd', 'rd', 'parse.page.olmocr',"
    " 'billed_api', 'r1', 'test:1', 'sk', 'ev', '{}', 0, 0, 'admitted', 1, 1)",
    "INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key, decision_id,"
    " driver, cost_class, dispatch_key, status, claimed_by, claimed_gen, lease_expires)"
    " VALUES(1, 'c:/x/a.pdf', 'p1', 'parse.page', 1, 'seed', 'd_1', 'parse.page.olmocr',"
    " 'billed_api', 'dk1', 'claimed', 'host:1:2.0', 1, 9999)",
    "INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key, decision_id,"
    " driver, cost_class, dispatch_key, status, claimed_by, claimed_gen, lease_expires)"
    " VALUES(2, 'c:/x/a.pdf', 'p2', 'parse.page', 1, 'seed2', 'd_1', 'parse.page.olmocr',"
    " 'billed_api', 'dk1', 'claimed', 'host:1:2.0', 1, 9999)",
)
"""The four rows `budget_reservation`'s foreign keys require: run, unit, decision, work.

`test_store_budget.py` seeds the same four with its own identifiers. Duplicated rather than shared,
because a fixture that two files reached into would make the identifiers a third file's fact -- and
these tests are about `admit()`'s arithmetic, which the ids do not enter.
"""


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[SqliteBudgetLedger]:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=1_700_000_000_000_000_000)
        with connection:
            for statement in _SEED:
                connection.execute(statement)
    finally:
        connection.close()
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        yield SqliteBudgetLedger(thread)


def _requests(
    estimate: Mapping[str, int],
    limits: Mapping[str, int],
    *,
    attempt: int = 1,
    part: str = "p1",
    work_id: int = 1,
) -> Any:
    return requests(
        estimate,
        limits=limits,
        scope="part",
        scope_key=f"c:/x/a.pdf#{part}",
        run_id="r_1",
        work_id=work_id,
        decision_id="d_1",
        attempt=attempt,
        claimed_gen=1,
        expires_ms=9_999,
        p95_multiple=P95,
    )


# ---------------------------------------------------------------------------------------------
# 1. The per-unit clamp -- the one dimension that scales
# ---------------------------------------------------------------------------------------------


PER_UNIT = {"micros_base": 4_000, "micros_per_part": 3_000, "micros_max": 16_000_000}


def test_the_per_unit_micros_cap_is_base_plus_per_part_times_part_count() -> None:
    """05:1288's own worked number: `4,000 + 3,000 x 5,000 = 15,004,000`."""
    assert per_unit_micros(PER_UNIT, part_count=5_000) == 15_004_000
    assert per_unit_micros(PER_UNIT, part_count=0) == 4_000
    assert per_unit_micros(PER_UNIT, part_count=1) == 7_000


def test_the_ceiling_wins_over_a_document_large_enough_to_pass_it() -> None:
    assert per_unit_micros(PER_UNIT, part_count=1_000_000) == 16_000_000


def test_a_ceiling_below_the_base_yields_the_ceiling() -> None:
    """The direction that cannot overspend: the operator's ceiling beats the operator's floor."""
    assert per_unit_micros({**PER_UNIT, "micros_max": 100}, part_count=3) == 100


def test_a_negative_policy_cannot_make_a_cap_that_grows_as_the_document_shrinks() -> None:
    assert per_unit_micros({**PER_UNIT, "micros_per_part": -9_000}, part_count=10) == 0


def test_the_three_keys_are_required_together() -> None:
    with pytest.raises(ValueError, match="micros_max"):
        per_unit_micros({"micros_base": 1, "micros_per_part": 1}, part_count=1)
    with pytest.raises(ValueError, match="not a count"):
        per_unit_micros(PER_UNIT, part_count=-1)


def test_no_other_per_unit_dimension_is_scaled_by_part_count(plan: PlanDocs) -> None:
    """05:2516: *"every other per_unit dimension is a scalar and is not scaled by part_count."*"""
    plan.require()
    assert plan.grep(
        r"every other per_unit dimension is a scalar", documents=("05-ingest-and-routing.md",)
    )
    assert set(PER_UNIT_MICROS_KEYS) == {"micros_base", "micros_per_part", "micros_max"}


# ---------------------------------------------------------------------------------------------
# 2. `requests()`: the declared dimensions, at the p95 ceiling, in a reproducible order
# ---------------------------------------------------------------------------------------------


PER_PART = {"micros": 6_000, "tokens_out": 24_000, "calls": 3, "gpu_ms": 12_000}


def test_only_the_declared_dimensions_get_a_row() -> None:
    """05:2523 reserves *"every other **declared** dimension"*: a declared cap is the trigger."""
    estimate = {"micros": 100, "tokens_out": 1_000, "calls": 1, "gpu_ms": 500, "tokens_in": 900}
    rows = _requests(estimate, PER_PART)
    assert [row.dim for row in rows] == ["micros", "tokens_out", "calls", "gpu_ms"]
    assert "tokens_in" not in {row.dim for row in rows}


def test_an_estimate_that_omits_a_capped_dimension_reserves_nothing_for_it() -> None:
    rows = _requests({"micros": 100}, PER_PART)
    assert [row.dim for row in rows] == ["micros"]


def test_the_two_output_proportional_dimensions_are_scaled_and_the_rest_are_not() -> None:
    """05:2470-2473, and `gpu_ms` is the subtle one: GPU time is proportional to output tokens."""
    estimate = {"micros": 100, "tokens_out": 1_000, "calls": 1, "gpu_ms": 500}
    amounts = {row.dim: row.amount for row in _requests(estimate, PER_PART)}
    assert amounts["tokens_out"] == 3_200
    assert amounts["gpu_ms"] == 1_600
    assert amounts["calls"] == 1
    assert amounts["micros"] == 100
    assert set(OUTPUT_PROPORTIONAL) == {"tokens_out", "gpu_ms"}
    assert "calls" in INPUT_PROPORTIONAL


def test_the_order_is_dims_order_and_not_the_estimates(plan: PlanDocs) -> None:
    """Two runs over one corpus must name the same bound dimension or `deferred_by_dim` is noise."""
    plan.require()
    backwards = {"gpu_ms": 1, "calls": 1, "tokens_out": 1, "micros": 1}
    rows = _requests(backwards, PER_PART)
    assert [row.dim for row in rows] == [d for d in DIMS if d in PER_PART]


def test_the_reservation_id_is_content_addressed_so_a_retried_reserve_is_idempotent() -> None:
    """08:2236: `reservation_id = 'res_' || sha256_canonical(identity)[:24]`."""
    first = _requests({"micros": 1}, PER_PART)[0]
    again = _requests({"micros": 1}, PER_PART)[0]
    later = _requests({"micros": 1}, PER_PART, attempt=2)[0]
    assert first.reservation_id == again.reservation_id
    assert first.reservation_id != later.reservation_id
    assert first.reservation_id == reservation_id(1, "d_1", 1, "micros")


def test_the_attempt_reaches_the_id_and_not_the_row() -> None:
    """`budget_reservation` carries no `attempt` column; the row is reachable from `work_id`."""
    row = _requests({"micros": 1}, PER_PART, attempt=7)[0]
    assert not hasattr(row, "attempt")
    assert row.work_id == 1


# ---------------------------------------------------------------------------------------------
# 3. `admit()`: steps 4, 5 and 6 against a real ledger
# ---------------------------------------------------------------------------------------------


def test_a_free_decision_reserves_nothing_and_never_reaches_the_ledger() -> None:
    """02:478's hop 8: *"`Admitted(reservations=())` -- a `free` decision reserves nothing."*"""

    class _Refuses:
        def reserve(self, *_a: object, **_k: object) -> str | None:
            raise AssertionError("a free admission must not take the write lock")

    verdict = admit((), ledger=_Refuses(), limits=PER_PART)  # type: ignore[arg-type]
    assert isinstance(verdict, Admitted)
    assert verdict.reservations == ()


def test_an_admission_holds_a_durable_row_per_dimension(ledger: SqliteBudgetLedger) -> None:
    rows = _requests({"micros": 100, "tokens_out": 1_000, "calls": 1, "gpu_ms": 500}, PER_PART)
    verdict = admit(rows, ledger=ledger, limits=PER_PART)
    assert isinstance(verdict, Admitted)
    assert len(verdict.reservations) == 4
    assert ledger.headroom("calls", "part", "c:/x/a.pdf#p1", 3) == 2


def test_the_first_exhausted_dimension_is_named_and_nothing_is_held(
    ledger: SqliteBudgetLedger,
) -> None:
    """05:2527 step 5, and the denial is total: a partial reservation holds headroom forever."""
    over = {"micros": 100, "tokens_out": 100_000, "calls": 1, "gpu_ms": 1}
    verdict = admit(_requests(over, PER_PART), ledger=ledger, limits=PER_PART)
    assert isinstance(verdict, Deferred)
    assert verdict.dim == "tokens_out"
    assert ledger.headroom("micros", "part", "c:/x/a.pdf#p1", 6_000) == 6_000


def test_a_deferral_leaves_the_work_claimable_and_the_cost_unchanged(
    ledger: SqliteBudgetLedger, tmp_path: Path
) -> None:
    """05:2532: *"the work row stays claimable and `cost_micros` is unchanged."*"""
    verdict = admit(_requests({"calls": 99}, PER_PART), ledger=ledger, limits=PER_PART)
    assert isinstance(verdict, Deferred)
    connection = ow.connect(tmp_path / "index.owstore")
    held = connection.execute("SELECT count(*) FROM budget_reservation").fetchone()[0]
    connection.close()
    assert held == 0


def test_an_uncapped_dimension_is_still_inserted_so_a_later_cap_reads_true(
    ledger: SqliteBudgetLedger,
) -> None:
    """*"its row is still inserted, so the held sum is already correct on the day a cap is
    declared for it."*
    """
    rows = _requests({"micros": 10, "calls": 1}, {"micros": 6_000, "calls": UNCAPPED})
    verdict = admit(rows, ledger=ledger, limits={"micros": 6_000})
    assert isinstance(verdict, Admitted)
    assert ledger.headroom("calls", "part", "c:/x/a.pdf#p1", 3) == 2


def test_two_parts_of_one_unit_have_two_budgets(ledger: SqliteBudgetLedger) -> None:
    """05:2523: *"per-part dimensions are charged per `(unit_part, lane)`."*

    Two parts are two `work` rows -- `work_identity` is `(unit_uri, unit_part, operator,
    op_version)` -- so the two reservations differ in `work_id` and their ids do not collide. The
    case that *does* collide is one work row at two scopes, below.
    """
    first = admit(_requests({"calls": 3}, PER_PART, part="p1"), ledger=ledger, limits=PER_PART)
    second = admit(
        _requests({"calls": 3}, PER_PART, part="p2", work_id=2), ledger=ledger, limits=PER_PART
    )
    assert isinstance(first, Admitted)
    assert isinstance(second, Admitted)
    assert ledger.headroom("calls", "part", "c:/x/a.pdf#p1", 3) == 0
    assert ledger.headroom("calls", "part", "c:/x/a.pdf#p2", 3) == 0


def test_one_work_row_at_two_scopes_collides_on_the_reservation_id(
    ledger: SqliteBudgetLedger,
) -> None:
    """08:2238's identity carries no scope, and `micros` is capped at two of them. **D173.**"""
    per_part = requests(
        {"micros": 100},
        limits={"micros": 6_000},
        scope="part",
        scope_key="c:/x/a.pdf#p1",
        run_id="r_1",
        work_id=1,
        decision_id="d_1",
        attempt=1,
        claimed_gen=1,
        expires_ms=9_999,
        p95_multiple=P95,
    )
    per_unit = requests(
        {"micros": 100},
        limits={"micros": 7_000},
        scope="unit",
        scope_key="c:/x/a.pdf",
        run_id="r_1",
        work_id=1,
        decision_id="d_1",
        attempt=1,
        claimed_gen=1,
        expires_ms=9_999,
        p95_multiple=P95,
    )
    assert per_part[0].reservation_id == per_unit[0].reservation_id
    with pytest.raises(ValueError, match="D173"):
        admit((*per_part, *per_unit), ledger=ledger, limits={"micros": 6_000})


def test_release_lifts_the_denial_that_just_fired(ledger: SqliteBudgetLedger) -> None:
    """05:2532's release-on-commit, in miniature: the gap is what buys concurrency back."""
    first = admit(_requests({"calls": 3}, PER_PART), ledger=ledger, limits=PER_PART)
    assert isinstance(first, Admitted)
    denied = admit(_requests({"calls": 1}, PER_PART, attempt=2), ledger=ledger, limits=PER_PART)
    assert isinstance(denied, Deferred)
    for reservation in first.reservations:
        ledger.release(reservation)
    again = admit(_requests({"calls": 1}, PER_PART, attempt=3), ledger=ledger, limits=PER_PART)
    assert isinstance(again, Admitted)


def test_a_committed_reservation_still_holds_what_it_actually_spent(
    ledger: SqliteBudgetLedger,
) -> None:
    """`headroom` is `limit - sum(held) - sum(committed)`: a commit is not a release."""
    verdict = admit(_requests({"calls": 3}, PER_PART), ledger=ledger, limits=PER_PART)
    assert isinstance(verdict, Admitted)
    assert ledger.commit(verdict.reservations[0], 1) is True
    assert ledger.headroom("calls", "part", "c:/x/a.pdf#p1", 3) == 2


# ---------------------------------------------------------------------------------------------
# 4. The worked trace at 02:563
# ---------------------------------------------------------------------------------------------


def _policy_block(plan: PlanDocs, table: str) -> Mapping[str, int]:
    """`[budget.per_part]` or `[budget.per_unit]`, parsed out of 05's own shipped-policy fence."""
    for body in plan.fences("05-ingest-and-routing.md", "toml"):
        if f"[{table}]" not in body:
            continue
        parsed = tomllib.loads(re.sub(r"^on_exhausted.*$", "", body, flags=re.MULTILINE))
        section = parsed
        for part in table.split("."):
            section = section[part]  # type: ignore[assignment]
        return {k: v for k, v in section.items() if isinstance(v, int)}
    raise AssertionError(f"05 ships no [{table}] block")


def test_the_worked_page_admission_reserves_the_four_dimensions_it_names(
    ledger: SqliteBudgetLedger, plan: PlanDocs
) -> None:
    """02:563's trace, executed: four reservations against `[budget.per_part]`'s four numbers."""
    plan.require()
    per_part = _policy_block(plan, "budget.per_part")
    assert per_part == PER_PART, "the constants above are 05:1279's own"

    estimate = {"micros": 2_732, "tokens_out": 6_000, "calls": 1, "gpu_ms": 3_000}
    verdict = admit(_requests(estimate, per_part), ledger=ledger, limits=per_part)
    assert isinstance(verdict, Admitted)
    assert len(verdict.reservations) == 4
    # The p95 ceiling: tokens_out and gpu_ms scaled, micros and calls not.
    assert ledger.headroom("tokens_out", "part", "c:/x/a.pdf#p1", 24_000) == 24_000 - 19_200
    assert ledger.headroom("gpu_ms", "part", "c:/x/a.pdf#p1", 12_000) == 12_000 - 9_600
    assert ledger.headroom("micros", "part", "c:/x/a.pdf#p1", 6_000) == 6_000 - 2_732


def test_calls_is_the_dimension_that_binds_first_on_this_pricebook(
    ledger: SqliteBudgetLedger, plan: PlanDocs
) -> None:
    """05:2489: *"what binds first on this pricebook is `[budget.per_part] calls = 3`."*"""
    plan.require()
    per_part = _policy_block(plan, "budget.per_part")
    estimate = {"micros": 1, "tokens_out": 1, "calls": 1, "gpu_ms": 1}
    for attempt in (1, 2, 3):
        assert isinstance(
            admit(_requests(estimate, per_part, attempt=attempt), ledger=ledger, limits=per_part),
            Admitted,
        )
    fourth = admit(_requests(estimate, per_part, attempt=4), ledger=ledger, limits=per_part)
    assert isinstance(fourth, Deferred)
    assert fourth.dim == "calls"


def test_the_per_unit_block_the_plan_ships_makes_the_cap_this_module_computes(
    plan: PlanDocs,
) -> None:
    plan.require()
    per_unit = _policy_block(plan, "budget.per_unit")
    assert per_unit_micros(per_unit, part_count=5_000) == 15_004_000
    assert per_unit["bytes_egress"] == 0, "0 = NO hosted escalation without a site-layer Grant"


# ---------------------------------------------------------------------------------------------
# 5. The three verdicts, and the column they are written to
# ---------------------------------------------------------------------------------------------


def test_the_three_admissions_are_the_columns_check_values(migrations: Path) -> None:
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    clause = re.search(r"admission\s+TEXT[^)]*CHECK\s*\(([^)]*)\)", ddl)
    assert clause is not None, "route_decision.admission carries a CHECK"
    assert set(re.findall(r"'([a-z_]+)'", clause.group(1))) == set(ADMISSIONS.values())


def test_each_verdict_projects_to_its_own_string() -> None:
    assert admission_of(Admitted(())) == "admitted"
    assert admission_of(Deferred("micros")) == "deferred"
    assert admission_of(Degraded((Degradation(kind="budget", message="clamped"),))) == "degraded"


def test_a_deferral_names_one_of_the_eight_dimensions() -> None:
    with pytest.raises(ValueError, match="eight dims"):
        Deferred("vibes")


def test_a_degraded_admission_carries_the_record_that_explains_it() -> None:
    """05:2519's three steps each name a kind; a record-free degradation is a silent downgrade."""
    with pytest.raises(ValueError, match="silent downgrade"):
        Degraded(())


def test_a_verdict_this_module_does_not_declare_has_no_admission_string() -> None:
    with pytest.raises(ValueError, match="admitted"):
        admission_of(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# 6. `budget.exhausted`, and the clause that keeps a p95 model honest
# ---------------------------------------------------------------------------------------------


def test_exhausted_is_written_only_with_no_sibling_reservation_in_flight() -> None:
    """05:2534, and 05:2545 is the arithmetic behind it: held rows carry 3.2x the eventual spend."""
    assert writes_exhausted(siblings_in_flight=0) is True
    assert writes_exhausted(siblings_in_flight=1) is False


def test_a_negative_sibling_count_is_not_a_count() -> None:
    with pytest.raises(ValueError, match="count of held rows"):
        writes_exhausted(siblings_in_flight=-1)


def test_the_clause_is_the_plans_own(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("05-ingest-and-routing.md"))
    assert "no sibling reservation still in flight for the same scope key" in text


# ---------------------------------------------------------------------------------------------
# 7. The defect report
# ---------------------------------------------------------------------------------------------


def test_the_first_exhausted_dimension_is_the_plans_first_and_the_plan_does_not_say_which(
    plan: PlanDocs,
) -> None:
    """05:2506 fixes an outcome and not an order; `DIMS` is what makes the outcome reproducible.

    **D174.** Two dimensions can both be short at once -- the shipped `[budget.per_part]` caps
    `micros` at 6,000 and `calls` at 3, and a decision estimating 7,000 micros over 4 calls exceeds
    both -- and which one is reported decides which knob the operator raises.
    """
    plan.require()
    heading = plan.grep(r"first exhausted dimension wins", documents=("05-ingest-and-routing.md",))
    assert heading, "05:2506's heading"
    ordered = plan.grep(
        r"first exhausted dimension.*(alphabetical|declared order|DIMS)",
        documents=("05-ingest-and-routing.md", "08-runtime.md", "02-architecture.md"),
    )
    assert not ordered, "no document says which dimension is checked first"
    # What ships: `Spend`'s printed order, so two runs agree.
    both_short = {"micros": 7_000, "calls": 4}
    assert next(row.dim for row in _requests(both_short, PER_PART)) == "micros"
    assert DIMS.index("micros") < DIMS.index("calls")
