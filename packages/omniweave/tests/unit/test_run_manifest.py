"""The run manifest, its bounded accumulators, and the two self-checks -- against the plan's own
numbers.

Four things in this file are transcriptions rather than inventions, and each says so at its own
docstring:

* `run.status`'s and `run.trigger`'s CHECK vocabularies are read out of `0004_runtime.sql` and
  compared to this module's two `Literal`s in both directions, because the manifest's `status` is
  the `run` row's `status` and a second spelling is how they drift.
* 15 section 2.2's Stage table is parsed for its `in stage_ms` column, so the seven that time are
  the seven the table marks `yes` -- not the seven someone typed.
* 08:95-99's `Outcome` -> `work.status` transition table is parsed for the four Outcomes that reach
  `done`, which is the fact `SPEND_AUDIT_SQL` is built on and the reason self-check 2 cannot be
  written entirely in SQL.
* `OBSERVE_KEYS` is compared against `SinkStats.as_manifest_fields()`, so the `observe.*` block has
  one home and this file proves it rather than asserting a list.

## The two tests that are defect reports

`test_a_resumed_attempt_is_billed_to_the_generation_that_first_decided_the_row` builds the state
08:507's resume produces -- a decision row stamped with generation 7, an attempt-2 spend row written
by generation 8 -- and shows `BILLED_MICROS_SQL` attributing the second run's money to the first
run's manifest. Against a real `.owstore`, with real rows, so it is a fact about the schema rather
than about a reading of it. D158.

`test_a_skipped_unchanged_row_is_indistinguishable_from_an_ok_row_in_sql` shows the other half of
the same shape: `work.status = 'done'` folds four Outcomes, the table has no `outcome` column, and a
check written entirely in SQL would flag rows that owe nothing. That is why `SpendAudit` carries the
Outcome from the runner's own `StepResult`.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import TYPE_CHECKING, Any, cast, get_args

import pytest
from omniweave.run import dispatch
from omniweave.run import manifest as manifest_module
from omniweave.run.manifest import (
    BILLED_MICROS_SQL,
    MANIFEST_DIR,
    MANIFEST_SUFFIX,
    MAX_OFFENDERS_SHOWN,
    OBSERVE_KEYS,
    PRICED_OUTCOMES,
    RUN_STATUSES,
    SPEND_AUDIT_SQL,
    TEMP_SUFFIX,
    TERMINAL_STATUSES,
    TRIGGERS,
    CacheStats,
    CostBlock,
    DegradationTally,
    ManifestWriter,
    Provenance,
    RunManifest,
    RunTally,
    SpendAudit,
    Timings,
    check_spend_audit,
    manifest_path,
    reconcile,
    render,
    unpriced,
)
from omniweave.run.supervisor import HostFacts
from omniweave_core.budget import DIMS as BUDGET_DIMS
from omniweave_core.cache import CacheVerdict
from omniweave_core.config import KEYS
from omniweave_core.errors import ConfigError, RouteError
from omniweave_core.events import EVENTS, STAGE_MS_KEYS, EventKind, SinkStats, Stage, TimedStage
from omniweave_core.observe.degradation import (
    DEGRADATION_KINDS,
    MAX_ROLLUP_PARTS,
    Degradation,
    DegradationKind,
    DegradationRollup,
    register_order,
    rollup,
)
from omniweave_core.operator import Outcome
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_ports.types import FailureClass

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import PlanDocs


RUNTIME_MIGRATION = "0004_runtime.sql"


def _ddl(migrations: Path) -> str:
    return (migrations / RUNTIME_MIGRATION).read_text(encoding="utf-8")


def _check_values(ddl: str, table: str, column: str) -> tuple[str, ...]:
    """The quoted members of one `CHECK (<column> IN (...))`, in DDL order.

    The DDL wraps, so the search runs over whitespace-collapsed text; the members are read with a
    string-literal regex rather than by splitting on commas, because `run.status`'s CHECK spans two
    lines and a comma-split would take the line break with it.
    """
    flat = " ".join(ddl.split())
    start = flat.index(f"CREATE TABLE {table} (")
    body = flat[start : flat.index(") STRICT", start)]
    clause = re.search(rf"CHECK \({column} IN \(([^)]*)\)\)", body)
    assert clause is not None, f"{table}.{column} has no CHECK (...) in {RUNTIME_MIGRATION}"
    return tuple(re.findall(r"'([a-z_]+)'", clause.group(1)))


# =============================================================================================
# 1. The two vocabularies the manifest borrows from the `run` row
# =============================================================================================


def test_run_statuses_are_the_run_rows_check_verbatim(migrations: Path) -> None:
    """`0004_runtime.sql:257-258`, read out of the DDL and compared in both directions.

    The manifest's `status` IS `run.status`: 15:33 makes `run.manifest_path` the pointer from the
    row to the file, so a manifest carrying a status the row's CHECK would refuse is a document that
    cannot be written back. Comparing as a tuple and not as a set also pins the order, which is what
    the error message in `RunManifest.__post_init__` prints.
    """
    assert _check_values(_ddl(migrations), "run", "status") == RUN_STATUSES


def test_triggers_are_the_run_rows_check_verbatim(migrations: Path) -> None:
    """The same, for `run.trigger` -- six members, the last two widened by charter section 5 C15."""
    assert _check_values(_ddl(migrations), "run", "trigger") == TRIGGERS


def test_running_is_the_one_non_terminal_status() -> None:
    assert frozenset(RUN_STATUSES) - {"running"} == TERMINAL_STATUSES
    assert len(TERMINAL_STATUSES) == 5


def test_timings_is_the_observe_key_the_config_declares() -> None:
    """`[observe] timings`'s two choices, read from the config declaration and not transcribed."""
    assert get_args(Timings) == KEYS["observe.timings"].choices


# =============================================================================================
# 2. `stage_ms`'s key set is 15 section 2.2's table, read from the table
# =============================================================================================


def _stage_table_rows(plan: PlanDocs) -> dict[str, str]:
    """15 section 2.2's Stage table as `{stage: in_stage_ms}`, read from the document.

    The table's last column is `in stage_ms` and its values are `yes`, `no: a read writes no
    manifest` and `no: a compile writes a receipt`. The row is identified by its first cell being a
    backticked lower-case word, which is how every row of that table opens and how the header and
    the separator row are excluded without matching on their text.
    """
    rows: dict[str, str] = {}
    for line in plan.lines("15-observability.md"):
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            continue
        name = cells[0].strip("`")
        if name in {stage.value for stage in Stage}:
            rows[name] = cells[4]
    return rows


def test_the_seven_that_time_are_the_seven_the_table_marks_yes(plan: PlanDocs) -> None:
    """15:105-113's `in stage_ms` column, and `query` and `compile` are the two that are not.

    Read from the table rather than transcribed: the point of the column is that two of the nine
    Stages produce no manifest entry, and a hand-typed seven would agree with the document only
    until somebody added a tenth Stage.
    """
    plan.require()
    rows = _stage_table_rows(plan)
    assert len(rows) == len(Stage), f"15 section 2.2's table has {len(rows)} of {len(Stage)} Stages"
    timed = tuple(name for name, verdict in rows.items() if verdict == "yes")
    assert timed == STAGE_MS_KEYS
    assert rows["query"].startswith("no"), rows["query"]
    assert rows["compile"].startswith("no"), rows["compile"]


def test_timed_stage_is_the_type_and_stage_ms_keys_is_its_projection() -> None:
    """One home: `STAGE_MS_KEYS` is derived from `TimedStage`, not written beside it.

    15:2191's glossary is the sentence under test -- the nine-member vocabulary's *"first seven
    members are the key set of `manifest.stage_ms`"* -- so the seven are asserted to be a PREFIX of
    `Stage`, which is stronger than asserting they are a subset.
    """
    members = get_args(TimedStage)
    assert tuple(stage.value for stage in members) == STAGE_MS_KEYS
    assert tuple(stage.value for stage in Stage)[: len(STAGE_MS_KEYS)] == STAGE_MS_KEYS


def test_closing_a_stage_outside_the_seven_is_refused_by_name() -> None:
    """A `query` Stage closed against a run tally is a confusion of two artefacts, not a no-op."""
    tally = RunTally()
    with pytest.raises(ConfigError, match="a read writes no manifest"):
        tally.stage_closed(Stage.QUERY, 12)
    with pytest.raises(ConfigError, match="a compile writes a receipt"):
        tally.stage_closed(Stage.COMPILE, 12)


def test_a_stage_entered_twice_sums_its_time_and_counts_its_entries() -> None:
    """15:116: *"`stage_ms[s]` is the SUM of the elapsed times of every `plan` span carrying that
    Stage"*, with `stage_entries[s]` beside it *"so a reader can tell one 600 s Stage from six 100 s
    ones"*. Both halves, with the plan's own example numbers."""
    tally = RunTally()
    for _ in range(6):
        tally.stage_closed(Stage.DERIVE, 100_000)
    tally.stage_closed(Stage.PARSE, 600_000)
    made = tally.snapshot(run_id="r_1")
    assert made.stage_ms[Stage.PARSE] == made.stage_ms[Stage.DERIVE] == 600_000
    assert made.stage_entries[Stage.PARSE] == 1
    assert made.stage_entries[Stage.DERIVE] == 6


def test_stage_ms_is_written_in_pipeline_order_not_alphabetical() -> None:
    """The module docstring's reason for not passing `sort_keys`, asserted on the bytes."""
    tally = RunTally()
    for stage in (Stage.MAINTAIN, Stage.PARSE, Stage.DISCOVER, Stage.CONVERGE):
        tally.stage_closed(stage, 1)
    document = json.loads(render(tally.snapshot(run_id="r_1")).decode("utf-8"))
    assert list(document["stage_ms"]) == ["discover", "parse", "converge", "maintain"]


def test_timings_never_omits_stage_ms_and_keeps_stage_entries() -> None:
    """15:120: `"never"` is *"the only supported way to get a manifest with no wall-clock content in
    it at all"*. `stage_entries` is a count and stays, which is what makes the switch lossy in
    exactly one dimension."""
    tally = RunTally()
    tally.stage_closed(Stage.PARSE, 651_000)
    made = tally.snapshot(run_id="r_1", timings="never")
    assert made.stage_ms == {}
    assert made.stage_entries[Stage.PARSE] == 1


def test_a_time_with_no_entry_count_beside_it_is_refused() -> None:
    with pytest.raises(ConfigError, match="no stage_entries beside them"):
        RunManifest(run_id="r_1", stage_ms={Stage.PARSE: 10})


def test_timings_never_with_a_populated_stage_ms_is_refused() -> None:
    with pytest.raises(ConfigError, match="15:120"):
        RunManifest(
            run_id="r_1",
            timings="never",
            stage_ms={Stage.PARSE: 10},
            stage_entries={Stage.PARSE: 1},
        )


# =============================================================================================
# 3. The document: ordering, closure, and the shape a killed run leaves
# =============================================================================================


def test_every_map_is_rebuilt_in_a_declared_order_so_two_runs_produce_one_document() -> None:
    """Determinism without `sort_keys`: two tallies fed the same facts in opposite orders render
    byte-identically. This is what makes `manifest.write`'s `sha256` a fact about the content."""
    forwards, backwards = RunTally(), RunTally()
    outcomes = (Outcome.OK, Outcome.CANCELLED, Outcome.OK_PARTIAL, Outcome.SKIPPED_CACHED)
    for outcome in outcomes:
        forwards.settled(outcome)
    for outcome in reversed(outcomes):
        backwards.settled(outcome)
    assert render(forwards.snapshot(run_id="r_1")) == render(backwards.snapshot(run_id="r_1"))


def test_outcomes_are_written_in_the_enums_declaration_order() -> None:
    tally = RunTally()
    for outcome in (Outcome.CANCELLED, Outcome.OK, Outcome.DEFERRED_BUDGET, Outcome.OK_PARTIAL):
        tally.settled(outcome, deferred_dim="micros")
    document = json.loads(render(tally.snapshot(run_id="r_1")).decode("utf-8"))
    assert list(document["outcomes"]) == ["ok", "ok_partial", "deferred_budget", "cancelled"]


def test_a_zero_count_and_an_absent_key_are_one_shape() -> None:
    """Two documents for one run is the thing `_ordered` drops zeros to prevent."""
    made = RunManifest(run_id="r_1", outcomes={Outcome.OK: 0, Outcome.CANCELLED: 3})
    assert dict(made.outcomes) == {Outcome.CANCELLED: 3}


def test_a_key_outside_a_closed_vocabulary_is_refused() -> None:
    """15:66 bounds the manifest by calling its largest members *"dicts keyed by a closed
    vocabulary"*. A typo'd key passed through is how such a bound stops holding."""
    with pytest.raises(ConfigError, match="outside the closed vocabulary"):
        RunManifest(run_id="r_1", deferred_by_dim={"dollars": 1})
    with pytest.raises(ConfigError, match="outside the closed vocabulary"):
        RunManifest(run_id="r_1", observe={"events_emmitted": 1})


def test_deferred_dimensions_are_the_budget_dims_and_micros_is_one() -> None:
    """`omniweave_core.budget.DIMS` has eight and the extra one over `Spend`'s seven is `micros`:
    a budget is declared in money, a driver reports none. 08:2273's *"deferred count by dimension"*
    is keyed by the budget's eight, so a run deferred for lack of money has a key to be counted
    under."""
    assert "micros" in BUDGET_DIMS
    tally = RunTally()
    tally.settled(Outcome.DEFERRED_BUDGET, deferred_dim="micros")
    assert dict(tally.snapshot(run_id="r_1").deferred_by_dim) == {"micros": 1}


def test_observe_keys_come_from_their_producer(plan: PlanDocs) -> None:
    """One home for the `observe.*` block, and 15:434's four are a subset of the six.

    The four the document names are read out of it rather than typed here, so the assertion is
    against the sentence that requires them: *"The manifest records what observability actually cost
    -- `observe.events_emitted`, `observe.events_dropped`, `observe.serialise_ns_total`,
    `observe.shard_bytes`."*
    """
    assert tuple(SinkStats().as_manifest_fields()) == OBSERVE_KEYS
    plan.require()
    named = {
        hit.text.split("`observe.")[1].split("`")[0]
        for hit in plan.grep(r"`observe\.[a-z_]+`", documents=("15-observability.md",))
    }
    assert named <= set(OBSERVE_KEYS), named - set(OBSERVE_KEYS)


def test_a_killed_run_leaves_a_running_manifest_with_no_end() -> None:
    """15:68: *"written at every Stage boundary and at every `degrade()`, so a killed run has one"*.
    The shape it leaves is the default, which is why `status` defaults to `running`."""
    made = RunManifest(run_id="r_1", started_ns=7)
    assert made.status == "running"
    assert made.ended_ns is None


def test_a_running_manifest_may_not_carry_an_end() -> None:
    with pytest.raises(ConfigError, match="a run that ended has a terminal status"):
        RunManifest(run_id="r_1", status="running", started_ns=1, ended_ns=2)


def test_an_end_before_the_start_is_refused() -> None:
    with pytest.raises(ConfigError, match="precedes started_ns"):
        RunManifest(run_id="r_1", status="ok", started_ns=9, ended_ns=8)


def test_a_manifest_carries_no_free_text_outside_a_degradation_exemplar() -> None:
    """The module docstring's first structural consequence of *"the manifest is not a log"*.

    Every leaf of the rendered document is an integer, a digest-shaped string, a closed-vocabulary
    member or `null` -- except inside `degradations[*].exemplar`, which is one `Degradation` per
    kind and carries the `message`, `knob` and `fix_command` the roll-up exists to preserve.
    """
    tally = RunTally()
    tally.degrade(Degradation(kind="budget", message="a sentence a human reads"), at_ns=1)
    document = json.loads(render(tally.snapshot(run_id="r_1")).decode("utf-8"))
    document["degradations"]["budget"].pop("exemplar")

    def leaves(value: object) -> list[object]:
        if isinstance(value, dict):
            return [leaf for item in value.values() for leaf in leaves(item)]
        if isinstance(value, list):
            return [leaf for item in value for leaf in leaves(item)]
        return [value]

    for leaf in leaves(document):
        assert leaf is None or isinstance(leaf, (int, str)), leaf
        if isinstance(leaf, str):
            assert " " not in leaf, f"a free-text leaf reached the manifest: {leaf!r}"


# =============================================================================================
# 4. `failures_by_class`, and the outcome that is not a failure
# =============================================================================================


def test_failures_by_class_counts_the_two_failed_outcomes_and_not_the_deferral() -> None:
    """08:2285: *"A denial is never a failure."* `DEFERRED_BUDGET` is an `Outcome` and it has a
    named path back to `pending`; folding it into the failure count would make the manifest's
    headline number the one an operator retries against -- *"which is the one thing that cannot
    help."*"""
    tally = RunTally()
    tally.settled(Outcome.FAILED_PERMANENT, failure_class=FailureClass.CORRUPT_INPUT)
    tally.settled(Outcome.FAILED_TRANSIENT, failure_class=FailureClass.TIMEOUT)
    tally.settled(Outcome.DEFERRED_BUDGET, deferred_dim="micros")
    made = tally.snapshot(run_id="r_1")
    assert dict(made.failures_by_class) == {
        FailureClass.CORRUPT_INPUT: 1,
        FailureClass.TIMEOUT: 1,
    }
    assert made.units == 3
    assert made.outcomes[Outcome.DEFERRED_BUDGET] == 1


def test_a_failed_outcome_without_its_class_is_refused() -> None:
    """`StepResult.__post_init__` requires a `FailureClass` on both `FAILED_*` outcomes, *"because
    the retry ladder escalates from the class's first cooldown and a classless transient failure has
    nothing to escalate from"*. The tally refuses the same thing rather than counting an absence."""
    tally = RunTally()
    with pytest.raises(ConfigError, match="no failure_class"):
        tally.settled(Outcome.FAILED_TRANSIENT)


def test_a_deferral_without_its_dimension_is_refused() -> None:
    tally = RunTally()
    with pytest.raises(ConfigError, match="no deferred_dim"):
        tally.settled(Outcome.DEFERRED_BUDGET)
    with pytest.raises(ConfigError, match="not a budget dimension"):
        tally.settled(Outcome.DEFERRED_BUDGET, deferred_dim="euros")


# =============================================================================================
# 5. The cache block -- five numbers projected from one verdict counter
# =============================================================================================


def test_hit_legacy_counts_as_a_hit_and_as_the_mixed_vintage_warning() -> None:
    """Counting it only as legacy would make `hits + misses` smaller than the number of units
    probed, and a reader checking that sum would find a hole."""
    tally = RunTally()
    for _ in range(3):
        tally.probed(CacheVerdict.HIT)
    tally.probed(CacheVerdict.HIT_LEGACY)
    tally.probed(CacheVerdict.MISS)
    stats = tally.snapshot(run_id="r_1").cache
    assert (stats.hits, stats.misses, stats.legacy_vintage_hits) == (4, 1, 1)


def test_hits_plus_misses_is_every_unit_probed() -> None:
    """The property the previous test's reasoning rests on, over all seven verdicts."""
    tally = RunTally()
    for verdict in CacheVerdict:
        tally.probed(verdict)
    stats = tally.snapshot(run_id="r_1").cache
    assert stats.hits + stats.misses == len(CacheVerdict)


def test_corrupt_entries_is_the_count_and_nothing_else_records_it(plan: PlanDocs) -> None:
    """08:1447: a corrupt blob is *"counted into `manifest.cache.corrupt_entries` and overwritten on
    the next success -- self-healing with no flag."* The count is the entire evidence it happened,
    which is why the field exists at all -- graphify *"re-billed a corrupt entry every run until
    #2405 counted it."*"""
    tally = RunTally()
    tally.probed(CacheVerdict.MISS_CORRUPT, rebilled=True)
    stats = tally.snapshot(run_id="r_1").cache
    assert (stats.corrupt_entries, stats.rebilled_units, stats.misses) == (1, 1, 1)
    plan.require()
    hits = plan.grep(r"self-healing with no flag", documents=("08-runtime.md",))
    assert len(hits) == 1, "08:1447's self-healing sentence moved"


def test_an_unknown_cache_verdict_is_refused_rather_than_dropped() -> None:
    with pytest.raises(ConfigError, match="not CacheVerdict members"):
        CacheStats.from_verdicts({"hit_maybe": 1})  # type: ignore[dict-item]


# =============================================================================================
# 6. The cost block -- three money figures and the one that is derivable
# =============================================================================================


def test_total_micros_is_billed_plus_op_and_a_stored_disagreement_is_refused() -> None:
    """08:2318-2321. `total_micros` is carried because the plan names it as a manifest figure, and
    checked because a figure that is both stored and derivable is one that can disagree with
    itself."""
    assert CostBlock.of(billed_micros=700, op_micros=41).total_micros == 741
    with pytest.raises(RouteError, match="08:2321"):
        CostBlock(billed_micros=700, op_micros=41, total_micros=700)


def test_op_spend_stays_out_of_billed_micros() -> None:
    """08:2583: `route_spend.decision_id` is `NOT NULL` and an `op.*` row's is NULL by CHECK, *"so a
    core-only step cannot have a route_spend row."* Adding its cost to `billed_micros` would fail
    self-check 1 on every run that ran `op.cluster`."""
    tally = RunTally()
    tally.spent(7_501_876)
    tally.op_spent(12_004)
    cost = tally.snapshot(run_id="r_1").cost
    assert cost.billed_micros == 7_501_876
    assert cost.op_micros == 12_004
    assert cost.total_micros == 7_513_880


def test_the_counterfactual_is_never_added_to_the_bill() -> None:
    """08:2298's third number. 15:798's worked line is the shape: a cache saved 68,818,054 micros
    against a 7,501,876 micro bill, and the bill is the smaller number."""
    tally = RunTally()
    tally.spent(7_501_876, would_have_been_micros=68_818_054)
    cost = tally.snapshot(run_id="r_1").cost
    assert cost.billed_micros == 7_501_876
    assert cost.would_have_been_micros_if_uncached == 68_818_054
    assert cost.total_micros == 7_501_876


def test_measured_and_apportioned_gpu_time_are_two_numbers(plan: PlanDocs) -> None:
    """15's extension 10: *"`cost.gpu_ms_apportioned` separated from `cost.gpu_ms_measured`"*,
    because a Service-backed driver cannot see the server's GPU time and one field would make a
    measurement and an estimate indistinguishable."""
    tally = RunTally()
    tally.spent(0, gpu_ms_measured=2_913_600)
    tally.spent(0, gpu_ms_apportioned=1_000)
    cost = tally.snapshot(run_id="r_1").cost
    assert (cost.gpu_ms_measured, cost.gpu_ms_apportioned) == (2_913_600, 1_000)
    plan.require()
    assert plan.grep(r"gpu_ms_apportioned.*separated from", documents=("15-observability.md",))


def test_negative_money_is_refused_at_every_door() -> None:
    tally = RunTally()
    with pytest.raises(RouteError, match="never negative"):
        tally.spent(-1)
    with pytest.raises(RouteError, match=r"an op\.\* row costing -1 micros"):
        tally.op_spent(-1)
    with pytest.raises(ConfigError, match="never negative"):
        CostBlock(billed_micros=-1, op_micros=0, total_micros=-1)


# =============================================================================================
# 7. The bounded accumulator -- 15:1118's whole point
# =============================================================================================


def test_the_tally_agrees_with_rollup_below_the_cap() -> None:
    """The two implementations pinned together. `rollup()` merges a sequence a caller already holds;
    `DegradationTally` accumulates without holding one, and below `MAX_ROLLUP_PARTS` they must
    produce the same entry or one of them is wrong."""
    records = tuple(
        Degradation(kind="budget", message="m", unit_uri=f"file:///u{i}", parts_affected=(i + 1,))
        for i in range(MAX_ROLLUP_PARTS)
    )
    tally = DegradationTally(records[0], at_ns=10)
    for record in records[1:]:
        tally.add(record, at_ns=10)
    assert tally.entry() == rollup(list(records), first_ns=10, last_ns=10)


def test_a_188_part_document_produces_one_bounded_entry() -> None:
    """15:1120, verbatim: *"a 188-part document can produce 188 `budget` records."* The entry is
    capped at `MAX_ROLLUP_PARTS`, `truncated` says so, and `n` still reports all 188 -- a reader
    never reads the cap as the total."""
    tally = DegradationTally(
        Degradation(kind="budget", message="first", unit_uri="file:///doc", parts_affected=(1,)),
        at_ns=100,
    )
    for part in range(2, 189):
        tally.add(
            Degradation(
                kind="budget", message="later", unit_uri="file:///doc", parts_affected=(part,)
            ),
            at_ns=100 + part,
        )
    entry = tally.entry()
    assert entry.n == 188
    assert len(entry.parts_affected) == MAX_ROLLUP_PARTS
    assert entry.truncated is True
    assert entry.units == ("file:///doc",)
    assert entry.exemplar.message == "first"
    assert (entry.first_ns, entry.last_ns) == (100, 288)


def test_the_accumulator_never_holds_the_records() -> None:
    """The unboundedness 15 section 6.3 refuses, asserted on the object rather than argued about.

    Every slot of a `DegradationTally` is a scalar or a container capped at `MAX_ROLLUP_PARTS + 1`,
    so feeding it ten thousand records grows it by nothing after the first sixty-five.
    """
    tally = DegradationTally(Degradation(kind="budget", message="m"), at_ns=1)
    for index in range(10_000):
        tally.add(
            Degradation(kind="budget", message="m", unit_uri=f"file:///u{index}"),
            at_ns=1 + index,
        )
    sizes = [
        len(value)
        for name in DegradationTally.__slots__
        if hasattr(value := getattr(tally, name), "__len__")
    ]
    assert max(sizes) <= MAX_ROLLUP_PARTS + 1
    assert tally.n == 10_001


def test_a_records_time_may_not_go_backwards() -> None:
    """15:1131 makes `first_ns`/`last_ns` *"host Clock at merge time -- injected, never ambient"*,
    and a monotonic reading does not go backwards."""
    tally = DegradationTally(Degradation(kind="budget", message="m"), at_ns=50)
    with pytest.raises(ConfigError, match="does not go backwards"):
        tally.add(Degradation(kind="budget", message="m"), at_ns=49)


def test_one_entry_is_one_kind() -> None:
    tally = DegradationTally(Degradation(kind="budget", message="m"), at_ns=1)
    with pytest.raises(ConfigError, match="one entry is one kind"):
        tally.add(Degradation(kind="quarantine", message="m"), at_ns=2)


def test_degradations_are_written_in_register_order() -> None:
    """`register_order`'s own docstring is the requirement: *"two runs that degraded the same way
    produce the same bytes."*"""
    tally = RunTally()
    for kind in ("calibration_stale", "budget", "quarantine"):
        tally.degrade(Degradation(kind=kind, message="m"), at_ns=1)  # type: ignore[arg-type]
    written = list(json.loads(render(tally.snapshot(run_id="r_1")).decode("utf-8"))["degradations"])
    assert written == sorted(written, key=register_order)
    assert written == ["budget", "quarantine", "calibration_stale"]


def test_an_entry_keyed_by_another_kind_is_refused() -> None:
    """`manifest.degradations[<kind>]` is only a true statement if the key IS the entry's kind."""
    entry = rollup([Degradation(kind="budget", message="m")], first_ns=1)
    with pytest.raises(ConfigError, match="the map key IS the entry's kind"):
        RunManifest(run_id="r_1", degradations={"quarantine": entry})


def test_the_manifest_is_at_most_twenty_seven_entries() -> None:
    """15:1139: *"`manifest.degradations` is therefore at most twenty-seven entries of bounded
    width, which is what makes it safe to rewrite the manifest incrementally."*"""
    tally = RunTally()
    for kind in DEGRADATION_KINDS:
        for index in range(200):
            # `DEGRADATION_KINDS` is `get_args(DegradationKind)`, so every member is one; the
            # annotation is what a static reader cannot follow through the tuple.
            tally.degrade(
                Degradation(kind=cast("DegradationKind", kind), message="m"), at_ns=1 + index
            )
    made = tally.snapshot(run_id="r_1")
    assert len(made.degradations) == 27
    assert sum(entry.n for entry in made.degradations.values()) == 27 * 200


def test_degraded_reads_the_seven_that_force_it() -> None:
    """`FORCES_DEGRADED` is the type's entire interface to the honest-absence contract, and the
    manifest reads it off the entries rather than storing a second boolean that could be wrong."""
    quiet = RunTally()
    quiet.degrade(Degradation(kind="budget", message="m"), at_ns=1)
    assert quiet.snapshot(run_id="r_1").degraded is False
    loud = RunTally()
    loud.degrade(Degradation(kind="calibration_stale", message="m"), at_ns=1)
    assert loud.snapshot(run_id="r_1").degraded is True


# =============================================================================================
# 8. The file: where it goes, how it is replaced, and what it announces
# =============================================================================================


def test_the_path_is_the_one_02_section_4_1_prints(tmp_path: Path) -> None:
    assert manifest_path(tmp_path, "r_01H") == tmp_path / MANIFEST_DIR / f"r_01H{MANIFEST_SUFFIX}"


@pytest.mark.parametrize("run_id", ["", ".", "..", "../escape", "a/b", "a\\b"])
def test_a_run_id_that_is_not_one_path_segment_is_refused(tmp_path: Path, run_id: str) -> None:
    """`ow why <run_id>` takes this argument from a user, so the traversal is refused at the one
    function both the writer and the reader resolve the path through."""
    with pytest.raises(ConfigError, match="one path segment"):
        manifest_path(tmp_path, run_id)


def test_the_write_is_atomic_and_leaves_no_staging_file(tmp_path: Path) -> None:
    """The sibling `.tmp` is gone after the replace, and the target holds the whole document."""
    path = manifest_path(tmp_path, "r_1")
    writer = ManifestWriter(path)
    digest = writer.write(RunManifest(run_id="r_1"))
    assert not path.with_name(path.name + TEMP_SUFFIX).exists()
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "r_1"
    assert len(digest) == 64


def test_the_staging_file_is_a_sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`os.replace` is atomic only within one filesystem, so the staging file is beside the target
    and not in the system temp directory. Asserted by catching it mid-write."""
    path = manifest_path(tmp_path, "r_1")
    seen: list[Path] = []
    original = manifest_module.Path.replace if hasattr(manifest_module, "Path") else None
    assert original is None  # `Path` is a TYPE_CHECKING import here; nothing to restore.

    real_write_bytes = type(path).write_bytes

    def spy(self: Path, data: bytes) -> int:
        seen.append(self)
        return real_write_bytes(self, data)

    monkeypatch.setattr(type(path), "write_bytes", spy)
    ManifestWriter(path).write(RunManifest(run_id="r_1"))
    assert seen == [path.with_name(path.name + TEMP_SUFFIX)]
    assert seen[0].parent == path.parent


def test_a_rewrite_that_changed_nothing_has_the_same_digest(tmp_path: Path) -> None:
    """The rewrite happens at every Stage boundary; a digest that changed on every write would make
    `manifest.write`'s `sha256` a fact about the clock rather than about the content."""
    writer = ManifestWriter(manifest_path(tmp_path, "r_1"))
    first = writer.write(RunManifest(run_id="r_1"))
    second = writer.write(RunManifest(run_id="r_1"))
    assert first == second
    assert writer.writes == 2
    assert writer.last_sha256 == second


def test_the_write_announces_path_and_sha256_and_nothing_else() -> None:
    """`tools/events.toml`'s `manifest.write` row is `fields = ["path", "sha256"]`, and that is the
    whole of it."""
    assert EVENTS[EventKind.MANIFEST_WRITE].fields == ("path", "sha256")


def test_a_sink_that_raises_does_not_lose_the_manifest(tmp_path: Path) -> None:
    """15 section 1 rule 1: the event stream is diagnostic and droppable; the file on disk is the
    artefact. So the emit happens after the replace and a failure to announce is not a failure to
    write."""
    path = manifest_path(tmp_path, "r_1")
    calls: list[dict[str, str]] = []

    def emit(**fields: str) -> None:
        calls.append(fields)
        raise RuntimeError("the sink is gone")

    with pytest.raises(RuntimeError):
        ManifestWriter(path, emit=emit).write(RunManifest(run_id="r_1"))
    assert path.exists()
    assert calls[0]["path"] == str(path)
    assert calls[0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_parent_directory_is_created_on_the_first_write(tmp_path: Path) -> None:
    """A run that fails before its first Stage boundary should not have left an empty `runs/`."""
    path = manifest_path(tmp_path, "r_1")
    assert not path.parent.exists()
    ManifestWriter(path).write(RunManifest(run_id="r_1"))
    assert path.parent.is_dir()


def test_the_bytes_end_in_one_newline_and_carry_no_carriage_return() -> None:
    """11-repo-layout.md section 1.9's third rule, applied to an artefact a CI Counter reads on a
    different operating system from the one that wrote it."""
    payload = render(RunManifest(run_id="r_1"))
    assert payload.endswith(b"\n")
    assert b"\r" not in payload
    assert payload.count(b"\n\n") == 0


# =============================================================================================
# 9. Self-check 1 -- exact, and the scope the ledger cannot express (D158)
# =============================================================================================


def test_reconcile_has_no_tolerance() -> None:
    """08:2291: *"Not within a tolerance -- every micro is attributable to exactly one
    `(unit, part, decision, attempt)` (I30)."*"""
    reconcile(7_501_876, 7_501_876)
    with pytest.raises(RouteError, match="the ledger holds more, by 1 micros"):
        reconcile(7_501_877, 7_501_876)
    with pytest.raises(RouteError, match="the manifest claims more, by 1 micros"):
        reconcile(7_501_875, 7_501_876)


def test_reconcile_names_the_direction_because_the_two_have_different_causes() -> None:
    with pytest.raises(RouteError) as ahead:
        reconcile(100, 0)
    assert "ledger holds more" in str(ahead.value)
    with pytest.raises(RouteError) as behind:
        reconcile(0, 100)
    assert "manifest claims more" in str(behind.value)


def _ledger(tmp_path: Path) -> Any:
    """A real `.owstore` with the four migrations applied, opened the way the store opens one.

    `omniweave_core.store.sqlite.connect` rather than `sqlite3.connect`: INV-17 puts the driver
    import in one module, and a test that reached around it would be asserting against a connection
    the runtime never uses -- different pragmas, different foreign-key enforcement, a different
    answer on a `STRICT` table.

    The return type is `Any` for the same invariant: it is a `sqlite3.Connection`, and TID251 bans
    naming that module here with no `TYPE_CHECKING` exemption. A ban that a type annotation could
    step around would not be one.
    """
    connection = ow.connect(tmp_path / "index.owstore")
    assert len(migrate.apply_pending(connection, now_ns=1)) == 4
    return connection


def _decision(conn: Any, decision_id: str, *, generation: int, content: str = "a" * 64) -> None:
    conn.execute(
        "INSERT INTO route_evidence(evidence_digest, payload, first_seen_at) VALUES (?, ?, 0)",
        (f"ev_{decision_id}", "{}"),
    )
    conn.execute(
        """INSERT INTO route_decision(
               decision_id, content_sha256, unit_part, lane, rung, policy_digest,
               pricebook_digest, hints_digest, read_set_digest, driver, cost_class, rule_id,
               rule_origin, slice_key, evidence_digest, est_spend, est_micros, reserved_micros,
               admission, generation, decided_at)
           VALUES (?, ?, '', 'text', 1, 'p', 'b', 'h', 'r', 'parse.pdf.pdfium', 'billed_api',
                   'rule', 'origin', 'slice', ?, '{}', 0, 0, 'admitted', ?, 0)""",
        (decision_id, content, f"ev_{decision_id}", generation),
    )


def test_a_resumed_attempt_is_billed_to_the_generation_that_first_decided_the_row(
    tmp_path: Path,
) -> None:
    """**D158.** `route_spend` has no run scope, so the only column `BILLED_MICROS_SQL` can filter
    on is `route_decision.generation` -- which names the generation that FIRST decided the row.

    08:507's resume is the state built here: generation 7 decides a row and pays attempt 1;
    generation 8 resumes, re-attempts the same decision (the identity is unchanged, and the insert
    is `ON CONFLICT ... DO NOTHING`), and writes attempt 2. The second run's money joins to the
    first run's generation. Generation 8's manifest reconciles against zero; generation 7's, already
    on disk and never rewritten, is now short by the amount somebody else spent.
    """
    conn = _ledger(tmp_path)
    _decision(conn, "dec_a", generation=7)
    conn.execute(
        "INSERT INTO route_spend(decision_id, attempt, micros, outcome) VALUES ('dec_a', 1, 500,"
        " 'failed_transient')"
    )
    conn.execute(
        "INSERT INTO route_spend(decision_id, attempt, micros, outcome) VALUES ('dec_a', 2, 300,"
        " 'ok')"
    )
    conn.commit()

    by_seven = conn.execute(BILLED_MICROS_SQL, {"generation": 7}).fetchone()[0]
    by_eight = conn.execute(BILLED_MICROS_SQL, {"generation": 8}).fetchone()[0]
    assert by_seven == 800, "the resumed attempt's 300 micros joined to generation 7"
    assert by_eight == 0, "generation 8 spent 300 micros and the ledger attributes it none"

    # The run that actually spent the 300 reconciles only against its own accumulation.
    tally = RunTally()
    tally.spent(300)
    reconcile(300, tally.snapshot(run_id="r_8").cost.billed_micros)
    with pytest.raises(RouteError, match="manifest claims more"):
        reconcile(by_eight, tally.snapshot(run_id="r_8").cost.billed_micros)


def test_the_decision_row_is_append_only_which_is_why_the_generation_is_the_first_ones(
    tmp_path: Path,
) -> None:
    """The mechanism behind D158, asserted on the schema: `route_decision_identity` is UNIQUE over
    the eight identity columns, so a second run computing the same decision cannot write a second
    row with its own generation."""
    conn = _ledger(tmp_path)
    _decision(conn, "dec_a", generation=7)
    conn.commit()
    with pytest.raises(Exception, match="UNIQUE constraint failed"):
        _decision(conn, "dec_b", generation=8)  # same identity columns, a new id


def test_billed_micros_sql_is_scoped_by_the_only_column_that_exists() -> None:
    """A reader of the statement should be able to see the limitation D158 reports."""
    flat = " ".join(BILLED_MICROS_SQL.split())
    assert "FROM route_spend s" in flat
    assert "JOIN route_decision d ON d.decision_id = s.decision_id" in flat
    assert "WHERE d.generation = :generation" in flat
    assert "run_id" not in flat


# =============================================================================================
# 10. Self-check 2 -- and why it cannot be written entirely in SQL
# =============================================================================================


def _outcome_to_status(plan: PlanDocs) -> dict[str, str]:
    """08:95-99's transition table as `{outcome: work.status}`, read from the document."""
    rows: dict[str, str] = {}
    values = {outcome.value for outcome in Outcome}
    for line in plan.lines("08-runtime.md"):
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            continue
        name = cells[0].strip("`")
        if name in values:
            rows[name] = cells[1].strip("`*").strip()
    return rows


def test_four_outcomes_reach_done_which_is_why_the_sql_cannot_narrow(plan: PlanDocs) -> None:
    """08:95-99, read out of the table. `work` has no `outcome` column, so `status = 'done'` is the
    narrowest predicate SQL can write and it covers four of the eight Outcomes -- of which only the
    two in `PRICED_OUTCOMES` owe a spend row."""
    plan.require()
    rows = _outcome_to_status(plan)
    assert len(rows) == len(Outcome), f"08's transition table has {len(rows)} of {len(Outcome)}"
    done = tuple(name for name, status in rows.items() if status == "done")
    assert done == ("ok", "ok_partial", "skipped_cached", "skipped_unchanged")
    assert tuple(outcome.value for outcome in PRICED_OUTCOMES) == done[:2]


def test_the_work_table_has_no_outcome_column(tmp_path: Path) -> None:
    """The other half of the same fact, asserted on the schema rather than on the prose."""
    conn = _ledger(tmp_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(work)")}
    assert "status" in columns
    assert "outcome" not in columns


def test_a_skipped_unchanged_row_is_indistinguishable_from_an_ok_row_in_sql(
    tmp_path: Path,
) -> None:
    """**The reason `SpendAudit` carries the runner's Outcome.** Two work rows settle `done` against
    the same decision -- one `ok` with a spend row, one `skipped_unchanged` with none -- and
    `SPEND_AUDIT_SQL` returns them in the same shape. Only the Outcome separates them, and the query
    cannot supply it."""
    conn = _ledger(tmp_path)
    conn.execute(
        "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen) "
        "VALUES('file:///a','planned','internal',1)"
    )
    _decision(conn, "dec_a", generation=1)
    for row_id, part in ((1, ""), (2, "p2")):
        conn.execute(
            """INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key,
                                decision_id, driver, cost_class, dispatch_key, status)
               VALUES (?, 'file:///a', ?, 'parse.pdf', 1, 'k', 'dec_a', 'parse.pdf.pdfium',
                       'billed_api', 'dk', 'done')""",
            (row_id, part),
        )
    conn.execute(
        "INSERT INTO route_spend(decision_id, attempt, micros, outcome) VALUES ('dec_a', 1, 42,"
        " 'ok')"
    )
    conn.commit()

    rows = conn.execute(SPEND_AUDIT_SQL).fetchall()
    assert sorted(rows) == [(1, "dec_a", 1), (2, "dec_a", 1)], rows

    audited = (
        SpendAudit(work_id=1, decision_id="dec_a", outcome=Outcome.OK, spend_rows=1),
        SpendAudit(work_id=2, decision_id="dec_a", outcome=Outcome.SKIPPED_UNCHANGED, spend_rows=0),
    )
    assert unpriced(audited) == ()


def test_a_left_join_is_what_surfaces_the_violation(tmp_path: Path) -> None:
    """An inner join would have hidden exactly the rows the check is about: a settled routed row
    with no spend row comes back with a count of zero, or it does not come back at all."""
    conn = _ledger(tmp_path)
    conn.execute(
        "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen) "
        "VALUES('file:///a','planned','internal',1)"
    )
    _decision(conn, "dec_a", generation=1)
    conn.execute(
        """INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key,
                            decision_id, driver, cost_class, dispatch_key, status)
           VALUES (7, 'file:///a', '', 'parse.pdf', 1, 'k', 'dec_a', 'parse.pdf.pdfium',
                   'billed_api', 'dk', 'done')"""
    )
    conn.commit()
    assert conn.execute(SPEND_AUDIT_SQL).fetchall() == [(7, "dec_a", 0)]
    assert unpriced(
        [SpendAudit(work_id=7, decision_id="dec_a", outcome=Outcome.OK, spend_rows=0)]
    ) == (7,)


def test_an_op_row_cannot_owe_a_spend_row(tmp_path: Path) -> None:
    """08:2583, and the `work` table's three pairing CHECKs make it structural: an `op.*` row's
    `decision_id` is NULL, so it never reaches `SPEND_AUDIT_SQL` at all and `unpriced()` skips it a
    second time. Flagging one would fail every run that ran `op.identify`."""
    conn = _ledger(tmp_path)
    conn.execute(
        "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen) "
        "VALUES('file:///a','planned','internal',1)"
    )
    conn.execute(
        """INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key,
                            decision_id, driver, cost_class, dispatch_key, status)
           VALUES (9, 'file:///a', '', 'op.identify', 1, 'k', NULL, NULL, 'free', NULL, 'done')"""
    )
    conn.commit()
    assert conn.execute(SPEND_AUDIT_SQL).fetchall() == []
    assert (
        unpriced([SpendAudit(work_id=9, decision_id=None, outcome=Outcome.OK, spend_rows=0)]) == ()
    )


def test_several_spend_rows_on_one_decision_is_not_a_violation() -> None:
    """05:2594: *"`[budget.per_part] calls = 3` is spent across attempts on one decision."* The
    check is *at least one*, not exactly one."""
    assert (
        unpriced([SpendAudit(work_id=1, decision_id="dec_a", outcome=Outcome.OK, spend_rows=3)])
        == ()
    )


def test_a_deferral_owes_no_spend_row() -> None:
    """`DEFERRED_BUDGET` was refused before it ran; a spend row would be money for nothing."""
    assert (
        unpriced(
            [
                SpendAudit(
                    work_id=1, decision_id="dec_a", outcome=Outcome.DEFERRED_BUDGET, spend_rows=0
                ),
                SpendAudit(work_id=2, decision_id="dec_a", outcome=Outcome.CANCELLED, spend_rows=0),
            ]
        )
        == ()
    )


def test_check_spend_audit_is_a_hard_failure_that_names_at_most_eight() -> None:
    """08:2295: *"A failure of either is a hard run failure, not a warning."* The message is bounded
    so a run that lost every spend row does not raise the corpus."""
    check_spend_audit([])
    rows = [
        SpendAudit(work_id=index, decision_id="dec_a", outcome=Outcome.OK, spend_rows=0)
        for index in range(1, 31)
    ]
    with pytest.raises(RouteError) as failure:
        check_spend_audit(rows)
    message = str(failure.value)
    assert "30 settled work row(s)" in message
    assert f"and {30 - MAX_OFFENDERS_SHOWN} more" in message
    assert "9," not in message.split("more", maxsplit=1)[0].split(":")[1]


def test_offenders_come_back_in_ascending_order() -> None:
    rows = [
        SpendAudit(work_id=work_id, decision_id="d", outcome=Outcome.OK_PARTIAL, spend_rows=0)
        for work_id in (40, 2, 17)
    ]
    assert unpriced(rows) == (2, 17, 40)


def test_the_sequence_half_of_check_two_is_homed_one_layer_down() -> None:
    """08:2293's *"a Sequence's apportionment sums to the session plus or minus one micro"* is
    `dispatch.check_apportionment`, called where the spend rows are written. This module does not
    restate it, and a second implementation is what this test exists to prevent."""
    assert callable(dispatch.check_apportionment)
    assert not hasattr(manifest_module, "check_apportionment")
    source = pathlib.Path(manifest_module.__file__).read_text(encoding="utf-8")
    assert "SEQUENCE_MICROS_TOLERANCE" not in source


# =============================================================================================
# 11. The generated contract
# =============================================================================================


def test_the_schema_publishes_the_closed_key_vocabularies(repo_root: Path) -> None:
    """15:66's bound, in the language-neutral contract. A `"type": "object"` with no
    `propertyNames` would publish a manifest in which `degradations` is unbounded, which is the one
    thing 15 section 1.1's argument rests on not being true."""
    document = json.loads(
        (repo_root / "schema" / "run-manifest-v1.json").read_text(encoding="utf-8")
    )
    assert document["properties"]["degradations"]["propertyNames"]["enum"] == list(
        DEGRADATION_KINDS
    )
    assert document["properties"]["stage_ms"]["propertyNames"]["enum"] == list(STAGE_MS_KEYS)
    assert document["properties"]["outcomes"]["propertyNames"]["enum"] == [
        outcome.value for outcome in Outcome
    ]
    assert document["properties"]["failures_by_class"]["propertyNames"]["enum"] == [
        member.value for member in FailureClass
    ]


def test_every_field_is_required_and_the_record_is_closed(repo_root: Path) -> None:
    document = json.loads(
        (repo_root / "schema" / "run-manifest-v1.json").read_text(encoding="utf-8")
    )
    assert document["additionalProperties"] is False
    assert document["required"] == list(document["properties"])
    assert set(document["$defs"]) == {
        "CacheStats",
        "CostBlock",
        "Degradation",
        "DegradationRollup",
        "HostFacts",
        "Provenance",
    }


def test_the_rendered_document_validates_against_its_own_required_list(repo_root: Path) -> None:
    """A structural check rather than a validator dependency: every key the schema requires is
    present in a rendered manifest, and no key is present that the schema does not declare."""
    document = json.loads(
        (repo_root / "schema" / "run-manifest-v1.json").read_text(encoding="utf-8")
    )
    rendered = json.loads(render(RunManifest(run_id="r_1")).decode("utf-8"))
    assert set(rendered) == set(document["required"])
    assert set(rendered["provenance"]) == set(document["$defs"]["Provenance"]["required"])
    assert set(rendered["host"]) == set(document["$defs"]["HostFacts"]["required"])
    assert set(rendered["cost"]) == set(document["$defs"]["CostBlock"]["required"])


def test_host_facts_reach_the_manifest_so_a_number_names_a_machine() -> None:
    """08:661: *"Measured ONCE at preflight and recorded in the run manifest, so a performance
    number is attributable to a machine."* A run that failed before preflight records zeros, which
    is not a machine and therefore reads as unmeasured."""
    measured = HostFacts(cpus=8, ram_bytes=1 << 34, free_disk_bytes=1 << 40, is_container=True)
    made = RunManifest(run_id="r_1", host=measured)
    assert made.host.cpus == 8
    assert RunManifest(run_id="r_1").host.cpus == 0


def test_provenance_carries_the_pricebook_the_bill_was_computed_against() -> None:
    """15:789: *"a bill without the price list it was computed against is not auditable."* The
    manifest outlives its store, so the digest travels with the number."""
    made = RunManifest(
        run_id="r_1",
        provenance=Provenance(pricebook_digest="4b1f9c2a", omniweave_version="1.0.0"),
    )
    document = json.loads(render(made).decode("utf-8"))
    assert document["provenance"]["pricebook_digest"] == "4b1f9c2a"


def test_a_degradation_rollup_reaches_the_schema_as_a_ref(repo_root: Path) -> None:
    """15:1128 prints `DegradationRollup` as *"the VALUE of one manifest.degradations[<kind>]
    entry"*, and the generated contract says the same thing."""
    document = json.loads(
        (repo_root / "schema" / "run-manifest-v1.json").read_text(encoding="utf-8")
    )
    value = document["properties"]["degradations"]["additionalProperties"]
    assert value == {"$ref": "#/$defs/DegradationRollup"}
    assert document["$defs"]["DegradationRollup"]["properties"]["exemplar"] == {
        "$ref": "#/$defs/Degradation"
    }
    assert set(DegradationRollup.__dataclass_fields__) == set(
        document["$defs"]["DegradationRollup"]["required"]
    )
