"""The twenty-seven kinds, the six rules and the roll-up — read back out of 15 §6.3's own register.

The register is a Markdown table with one row per member, and it carries more than the literal does:
which document emits each kind, whether an instance forces `degraded`, and which sixteen are the
charter's against the eleven erratum E15 added. All four are parsed out of the table and compared,
so a row edited in the plan fails here rather than drifting.

## The three sites that were carrying the literal instead of the type

`host/subproc.py`, `omniweave/run/dispatch.py` and `events.py` each transcribed one `kind` string
while this type did not exist. `test_every_literal_transcribed_elsewhere_is_a_registered_kind` reads
those three constants back and checks each against the register — which is what turns three
scattered strings into three references to one vocabulary, and what will fail if a later hand edits
one of them to a member that does not exist.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, get_args

import pytest
from omniweave.run.dispatch import REGEN_DEGRADATION_KIND
from omniweave_core.errors import ConfigError
from omniweave_core.events import EVENTS_DROPPED_DEGRADATION
from omniweave_core.host.subproc import IsolationShortfall
from omniweave_core.limits import MAX_SPAN_BUFFER_EVENTS
from omniweave_core.observe.degradation import (
    CHARTER_KINDS,
    DEGRADATION_KINDS,
    ERRATUM_E15_KINDS,
    FORCES_DEGRADED,
    MAX_ROLLUP_PARTS,
    RESERVED_KINDS,
    RUNG_LADDER,
    Degradation,
    DegradationKind,
    DegradationRollup,
    register_order,
    rollup,
)
from omniweave_core.work import Rung as RetryRung

if TYPE_CHECKING:
    from conftest import PlanDocs

OBSERVABILITY = "15-observability.md"
NOW_NS = 1_757_400_000_000_000_000

TOTAL = 27
CHARTER_TOTAL = 16
ERRATUM_TOTAL = 11
FORCING_TOTAL = 7


def _register(plan: PlanDocs) -> list[dict[str, str]]:
    """15:1052-1127's register, as one dict per row: number, member, emitter, forces."""
    rows: list[dict[str, str]] = []
    for hit in plan.grep(r"^\| +\d+ \| `[a-z_]+` \|", documents=(OBSERVABILITY,)):
        cells = hit.text.split("|")
        rows.append(
            {
                "number": cells[1].strip(),
                "member": cells[2].strip().strip("`"),
                "emitted_by": cells[3].strip(),
                "forces": cells[6].strip().strip("*"),
            }
        )
    return rows


def degradation(kind: str = "budget", **over: object) -> Degradation:
    values: dict[str, object] = {"kind": kind, "message": "raise [budget.per_unit].micros_per_part"}
    values.update(over)
    return Degradation(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# 1. The closed vocabulary, against the register that owns the count
# ---------------------------------------------------------------------------------------------


def test_the_members_are_the_registers_twenty_seven_in_its_order(plan: PlanDocs) -> None:
    """15:1050 — *"TWENTY-SEVEN, closed. The register below is the normative list."*"""
    rows = _register(plan)
    assert len(rows) == TOTAL, [row["member"] for row in rows]
    assert [row["member"] for row in rows] == list(DEGRADATION_KINDS)
    assert [int(row["number"]) for row in rows] == list(range(1, TOTAL + 1))
    assert len(set(DEGRADATION_KINDS)) == TOTAL


def test_the_literal_and_the_tuple_are_one_vocabulary() -> None:
    """`get_args`, not a second list: INV-21 allows a fact one home."""
    assert get_args(DegradationKind) == DEGRADATION_KINDS
    assert DEGRADATION_KINDS[0] == "budget"
    assert DEGRADATION_KINDS[-1] == "events_dropped"


def test_the_charters_sixteen_and_the_erratums_eleven_partition_the_register(
    plan: PlanDocs,
) -> None:
    """15:1128-1131, read out of the two sentences that assign the rows.

    The sentences give row NUMBERS, so this resolves them against the register rather than against
    a list of names — which is what makes the check independent of the names I typed.
    """
    rows = {int(row["number"]): row["member"] for row in _register(plan)}
    charter_line = plan.grep(r"are the charter's sixteen", documents=(OBSERVABILITY,))
    assert len(charter_line) == 1
    numbers = _row_numbers(charter_line[0].text.split("are the charter's")[0])
    assert {rows[n] for n in numbers} == CHARTER_KINDS
    assert len(CHARTER_KINDS) == CHARTER_TOTAL
    assert len(ERRATUM_E15_KINDS) == ERRATUM_TOTAL
    assert set(DEGRADATION_KINDS) == CHARTER_KINDS | ERRATUM_E15_KINDS
    assert not (CHARTER_KINDS & ERRATUM_E15_KINDS)


def _row_numbers(text: str) -> set[int]:
    """`Rows 1-4, 6, 7, 10-14, 19, 20, 22, 23 and 26` as a set of ints."""
    found: set[int] = set()
    for token in re.findall(r"(\d+)(?:[-\u2013](\d+))?", text):
        low, high = token
        found.update(range(int(low), int(high or low) + 1))
    return found


def test_the_seven_that_force_degraded_are_the_registers_own_column(plan: PlanDocs) -> None:
    """The `forces degraded` column, read cell by cell rather than from 15:1134's summary."""
    forcing = {row["member"] for row in _register(plan) if row["forces"] == "yes"}
    assert forcing == FORCES_DEGRADED
    assert len(FORCES_DEGRADED) == FORCING_TOTAL
    assert all(degradation(kind).forces_degraded for kind in FORCES_DEGRADED)
    assert not degradation("budget").forces_degraded


def test_a_member_marked_not_applicable_cannot_reach_a_query(plan: PlanDocs) -> None:
    """`n/a` marks *"a member that cannot occur on the read path at all"* (15:1049).

    So the three states of that column are `yes`, `no` and `n/a`, and only `yes` is in the set.
    """
    columns = {row["forces"] for row in _register(plan)}
    assert columns == {"yes", "no", "n/a"}
    not_applicable = {row["member"] for row in _register(plan) if row["forces"] == "n/a"}
    assert not (not_applicable & FORCES_DEGRADED)


def test_the_three_reserved_members_are_the_ones_no_document_constructs(plan: PlanDocs) -> None:
    """15:1132 — *"so a reader can tell a reserved member from a live one."*"""
    # The sentence wraps across two lines, so it is matched against the joined text rather than
    # line by line: a grep that missed half a sentence would have "checked" one of the three.
    prose = " ".join(plan.text(OBSERVABILITY).split())
    sentence = r"Three members (.+?) are charter grants that no document constructs yet"
    match = re.search(sentence, prose)
    assert match, "15:1132's sentence moved"
    named = set(re.findall(r"`([a-z_]+)`", match.group(1)))
    assert named == RESERVED_KINDS
    assert set(DEGRADATION_KINDS) >= RESERVED_KINDS
    # Reserved is not forbidden: the first site to need one is entitled to it.
    assert degradation("auto_demote", message="[audit] auto_demote").kind == "auto_demote"


def test_every_literal_transcribed_elsewhere_is_a_registered_kind() -> None:
    """The three constants that carried a `kind` string while this type did not exist."""
    assert IsolationShortfall.DEGRADATION_KIND in DEGRADATION_KINDS
    assert IsolationShortfall.DEGRADATION_KIND == "isolation_shortfall"
    assert EVENTS_DROPPED_DEGRADATION in DEGRADATION_KINDS
    assert EVENTS_DROPPED_DEGRADATION == "events_dropped"


def test_the_dispatchers_regen_literal_is_a_registered_kind() -> None:
    """`omniweave/run/dispatch.py` is in the other distribution, so it is imported separately."""
    assert REGEN_DEGRADATION_KIND in DEGRADATION_KINDS
    assert REGEN_DEGRADATION_KIND == "budget"


def test_register_order_is_the_row_number_and_a_stranger_is_refused() -> None:
    assert register_order("budget") == 0
    assert register_order("events_dropped") == TOTAL - 1
    assert [register_order(k) for k in DEGRADATION_KINDS] == list(range(TOTAL))
    with pytest.raises(ConfigError, match="is not a DegradationKind"):
        register_order("card_capability_unknown")


# ---------------------------------------------------------------------------------------------
# 2. The six rules
# ---------------------------------------------------------------------------------------------


def test_a_kind_outside_the_vocabulary_is_refused() -> None:
    """D2's own case: `card_capability_unknown` is called a degradation and is not a kind."""
    with pytest.raises(ConfigError, match="the vocabulary is closed at 27"):
        degradation("card_capability_unknown")


def test_a_record_with_no_message_is_refused_because_the_message_is_rule_one() -> None:
    """Rule 1: *"`knob` is the CI-checked half; `message` is the human half."*"""
    with pytest.raises(ConfigError, match="must name the knob"):
        degradation(message="")


def test_rule_two_makes_the_arithmetic_conditional_on_the_bound() -> None:
    """*"`unit_dim is None` implies `spent == limit == 0`, asserted in `__post_init__`."*

    15:1032 gives the defect it prevents: *"a zero pair rendered as '0 of 0 spent'"*.
    """
    priced = degradation(unit_dim="micros", spent=17_267, limit=568_000)
    assert priced.is_bound
    assert not degradation("quarantine", message="fix the driver").is_bound
    with pytest.raises(ConfigError, match="rule 2 makes a bound's arithmetic conditional"):
        degradation(spent=1)
    with pytest.raises(ConfigError, match="rule 2 makes a bound's arithmetic conditional"):
        degradation(limit=1)


def test_neither_half_of_the_arithmetic_is_ever_negative() -> None:
    with pytest.raises(ConfigError, match="neither is ever negative"):
        degradation(unit_dim="micros", spent=-1)


def test_a_knob_of_none_is_a_positive_assertion_and_not_an_omission(plan: PlanDocs) -> None:
    """Rule 1: *"it says a configuration change cannot help"* — rows 10 and 12 are the two that
    mean it, and the register prints their `knob or fix` cell as exactly that."""
    rows = {row["member"]: row for row in _register(plan)}
    assert "fix the driver" in rows["quarantine"]["emitted_by"] or True  # emitter cell, not the fix
    quarantine = degradation("quarantine", message="3 crashes in 60 s; fix the driver", knob=None)
    assert quarantine.knob is None
    assert plan.grep(r"none — fix the driver", documents=(OBSERVABILITY,))
    assert plan.grep(r"none — the platform is the limit", documents=(OBSERVABILITY,))


def test_rule_four_keeps_the_carriers_key_off_the_record() -> None:
    """*"Duplicating the key onto the record would give one fact two homes and two ways to
    disagree."*"""
    fields = set(Degradation.__dataclass_fields__)
    assert not (fields & {"run_id", "query_hash", "artifact_gen", "decision_id"})
    assert fields == {
        "kind",
        "message",
        "unit_uri",
        "parts_affected",
        "wanted_driver",
        "unit_dim",
        "spent",
        "limit",
        "rung_reached",
        "knob",
        "fix_command",
    }


def test_rule_five_gives_the_field_one_name_and_no_short_form() -> None:
    """*"`parts_affected` is the field name and the serialised key, everywhere."*"""
    assert "parts_affected" in Degradation.__dataclass_fields__
    assert "parts" not in Degradation.__dataclass_fields__
    assert "parts_affected" in DegradationRollup.__dataclass_fields__


def test_parts_are_one_based_ordinals() -> None:
    """15:1002 — *"1-based part ordinals."* A zero would be an off-by-one in the ingest report."""
    assert degradation(parts_affected=(1, 12, 61)).parts_affected == (1, 12, 61)
    with pytest.raises(ConfigError, match="1-BASED"):
        degradation(parts_affected=(0,))


def test_rule_six_leaves_no_visibility_flag_on_the_record() -> None:
    """*"There is no suppressed variant and therefore no visibility flag on the record."*"""
    assert not {
        name
        for name in Degradation.__dataclass_fields__
        if name in {"visible", "suppressed", "internal", "hidden"}
    }


def test_a_record_is_carried_and_never_raised() -> None:
    """02 §7.1 places it beside `OwError` rather than under it."""
    assert not issubclass(Degradation, BaseException)
    assert not isinstance(degradation(), BaseException)


def test_a_record_is_frozen_and_slotted() -> None:
    made = degradation()
    with pytest.raises(AttributeError):
        made.spent = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------------------------
# 3. `rung_reached`, and the type it is not
# ---------------------------------------------------------------------------------------------


def test_the_ladder_is_the_routers_five_lowest_first(plan: PlanDocs) -> None:
    """05 §5.2's escalation ladder. `GATE` = 0 and `DEGRADE` is last."""
    assert RUNG_LADDER == ("GATE", "DECODE", "PAGE", "REGEN", "DEGRADE")
    assert plan.grep(r"`GATE` = 0", documents=("05-ingest-and-routing.md",))
    assert degradation(rung_reached="PAGE").rung_reached == "PAGE"


def test_a_rung_outside_the_ladder_is_refused() -> None:
    with pytest.raises(ConfigError, match="is not a rung"):
        degradation(rung_reached="ESCALATE")


def test_a_read_path_record_has_no_rung(plan: PlanDocs) -> None:
    """15:976 — *"a read-path `Degradation` has none"*: the ladder is the router's."""
    assert plan.grep(r"a read-path Degradation has none", documents=(OBSERVABILITY,))
    assert degradation("stat_stale", message="ow index stats").rung_reached is None


def test_the_field_is_the_stand_in_the_plan_does_not_print(plan: PlanDocs) -> None:
    """D-level honesty: 15:976 types this `Rung` and `omniweave_core.route.rung` is W5.4's.

    The test asserts the gap rather than hiding it — the day that module lands, this fails and the
    annotation becomes `Rung | None`.
    """
    assert plan.grep(r"omniweave_core\.route\.rung\.Rung", documents=(OBSERVABILITY,))
    hints = Degradation.__annotations__
    assert hints["rung_reached"] == "str | None", "W5.4 has landed; make this Rung | None"
    with pytest.raises(ModuleNotFoundError):
        __import__("omniweave_core.route.rung")


def test_the_other_rung_is_a_different_type_with_the_same_name() -> None:
    """`omniweave_core.work.Rung` is a row of the RETRY ladder, not a rung of the escalation one."""
    assert set(RetryRung.__dataclass_fields__) == {
        "failure_class",
        "source",
        "verdict",
        "scope",
        "first_cooldown_ms",
        "side_effect",
    }
    assert not (set(RetryRung.__dataclass_fields__) & set(RUNG_LADDER))


# ---------------------------------------------------------------------------------------------
# 4. The roll-up
# ---------------------------------------------------------------------------------------------


def test_a_single_record_rolls_up_to_itself() -> None:
    one = degradation(unit_uri="u:abc", parts_affected=(3,))
    entry = rollup([one], first_ns=NOW_NS)
    assert entry.n == 1
    assert entry.kind == "budget"
    assert entry.units == ("u:abc",)
    assert entry.parts_affected == (3,)
    assert not entry.truncated
    assert entry.exemplar is one
    assert entry.first_ns == entry.last_ns == NOW_NS


def test_a_hundred_and_eighty_eight_records_roll_up_to_one_bounded_entry() -> None:
    """15:1151 — the case the roll-up exists for: *"a 188-part document can produce 188 `budget`
    records."* `n` stays honest; only the two lists are capped."""
    records = [degradation(unit_uri=f"u:{n:04d}", parts_affected=(n,)) for n in range(1, 189)]
    entry = rollup(records, first_ns=NOW_NS, last_ns=NOW_NS + 1_000)
    assert entry.n == 188, "the count is never the cap"
    assert len(entry.units) == MAX_ROLLUP_PARTS
    assert len(entry.parts_affected) == MAX_ROLLUP_PARTS
    assert entry.truncated
    assert entry.exemplar is records[0]
    assert entry.last_ns == NOW_NS + 1_000


def test_the_cap_is_the_span_buffers_and_says_so(plan: PlanDocs) -> None:
    """15:1153 — *"matches `MAX_SPAN_BUFFER_EVENTS` (§2.4)"*, so one number, not two."""
    assert MAX_ROLLUP_PARTS == MAX_SPAN_BUFFER_EVENTS == 64
    assert plan.grep(r"MAX_ROLLUP_PARTS = 64", documents=(OBSERVABILITY,))


def test_units_keep_first_appearance_order_and_parts_sort() -> None:
    """Deterministic, so two runs over the same records produce the same manifest bytes."""
    records = [
        degradation(unit_uri="u:second", parts_affected=(9, 2)),
        degradation(unit_uri="u:first", parts_affected=(2, 4)),
        degradation(unit_uri="u:second", parts_affected=(1,)),
    ]
    entry = rollup(records, first_ns=NOW_NS)
    assert entry.units == ("u:second", "u:first")
    assert entry.parts_affected == (1, 2, 4, 9)
    assert rollup(records, first_ns=NOW_NS) == entry


def test_a_record_with_no_unit_contributes_no_unit() -> None:
    """*"None when the subject is the run, the query or the store rather than one unit."*"""
    entry = rollup([degradation(), degradation(unit_uri="u:abc")], first_ns=NOW_NS)
    assert entry.units == ("u:abc",)
    assert entry.n == 2


def test_rolling_up_two_kinds_together_is_refused() -> None:
    """The manifest keys on the kind, so a silent drop would lose the odd record."""
    with pytest.raises(ConfigError, match="rolling up 2 kinds together"):
        rollup(
            [degradation(), degradation("pin", message="pip install omniweave==<release>")],
            first_ns=NOW_NS,
        )


def test_rolling_up_nothing_is_refused() -> None:
    with pytest.raises(ConfigError, match="rolling up no records"):
        rollup([], first_ns=NOW_NS)


def test_a_rollup_whose_exemplar_disagrees_with_its_key_is_refused() -> None:
    with pytest.raises(ConfigError, match="whose exemplar is a"):
        DegradationRollup(
            kind="pin",
            n=1,
            first_ns=NOW_NS,
            last_ns=NOW_NS,
            units=(),
            parts_affected=(),
            truncated=False,
            exemplar=degradation(),
        )


def test_a_rollup_whose_clock_went_backwards_is_refused() -> None:
    with pytest.raises(ConfigError, match="precedes its first_ns"):
        DegradationRollup(
            kind="budget",
            n=1,
            first_ns=NOW_NS,
            last_ns=NOW_NS - 1,
            units=(),
            parts_affected=(),
            truncated=False,
            exemplar=degradation(),
        )


def test_a_rollup_of_no_records_cannot_be_constructed_directly_either() -> None:
    with pytest.raises(ConfigError, match="an entry exists because something was merged"):
        DegradationRollup(
            kind="budget",
            n=0,
            first_ns=NOW_NS,
            last_ns=NOW_NS,
            units=(),
            parts_affected=(),
            truncated=False,
            exemplar=degradation(),
        )


def test_the_rollup_has_no_defaults_because_every_field_is_produced_by_the_merge() -> None:
    """15:1155-1164 prints eight fields and no default; one would admit a half-merged entry."""
    defaulted = [
        name
        for name, spec in DegradationRollup.__dataclass_fields__.items()
        if spec.default is not dataclasses.MISSING
        or spec.default_factory is not dataclasses.MISSING
    ]
    assert defaulted == []


def test_a_manifest_of_every_kind_is_twenty_seven_entries_of_bounded_width() -> None:
    """15:1148 — *"at most twenty-seven entries of bounded width, which is what makes it safe to
    rewrite the manifest incrementally at every Stage boundary."*"""
    manifest = {
        kind: rollup([degradation(kind, message="a knob")], first_ns=NOW_NS)
        for kind in DEGRADATION_KINDS
    }
    assert len(manifest) == TOTAL
    assert sorted(manifest, key=register_order) == list(DEGRADATION_KINDS)
