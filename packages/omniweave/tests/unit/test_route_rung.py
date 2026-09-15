"""`omniweave.route.rung` against 05-ingest-and-routing.md Part 3's table and INV-21.

Two things are worth testing here and the rest is a transcription. The ORDINALS are load-bearing --
`DEGRADE` above `PAGE` while running a cheaper driver is the whole reason `Rung` and `Spend` are
separate types -- and `LANES` is DERIVED, which a comment can claim and only a test can hold.
"""

from __future__ import annotations

import pytest
from omniweave.route.rung import LANES, PARSE_LANES, RUNG_BY_NAME, TERMINAL_RUNGS, Rung
from omniweave_core.model.enums import Lane


def test_the_seven_rungs_in_the_plans_order_with_the_plans_ordinals() -> None:
    """05:838-844's table, top to bottom. The integers are in the plan, not chosen here."""
    assert [(member.name, member.value) for member in Rung] == [
        ("GATE", 0),
        ("DECODE", 1),
        ("REPAIR", 2),
        ("PAGE", 3),
        ("REGEN", 4),
        ("DEGRADE", 5),
        ("ENRICH", 6),
    ]


def test_degrade_is_a_forward_move_although_it_runs_a_cheaper_driver() -> None:
    """05:862, the property that makes `child.rung > parent.rung` enforceable in SQL.

    A page that escalated to `PAGE` and then degraded has `5 > 3`, so RT8's trigger accepts the
    child row -- while the driver that ran is `parse.pdf.pdfium`, which is cheaper than the model
    call at rung 3. The assertion is the arithmetic; the cost is `Spend`'s and is not here.
    """
    assert Rung.DEGRADE > Rung.PAGE
    assert Rung.DEGRADE > Rung.DECODE


def test_the_ladder_compares_as_integers_which_is_why_it_is_an_intenum() -> None:
    """05:1090's loop is `for rung in GATE, DECODE, ...` and never revisits; sorting must agree."""
    assert sorted(Rung, key=int) == list(Rung)
    assert Rung.GATE < Rung.DECODE < Rung.REPAIR < Rung.PAGE < Rung.REGEN
    assert int(Rung.ENRICH) == 6


def test_rung_by_name_is_the_policy_grammars_screaming_snake_spelling() -> None:
    """05:1216: *"`rung = "GATE"` and the other `Rung` literals are written SCREAMING_SNAKE"*."""
    assert RUNG_BY_NAME["DECODE"] is Rung.DECODE
    assert set(RUNG_BY_NAME) == {member.name for member in Rung}
    assert "decode" not in RUNG_BY_NAME


def test_terminal_rungs_holds_only_the_unconditional_two() -> None:
    """`GATE` and `DECODE` are terminal CONDITIONALLY and are therefore not members.

    A set that folded a conditional terminal into an unconditional one would tell the rung loop to
    stop after a `GATE` rule that merely clamped `max_cost_class`, which is 05:1051's whole point
    about clamps: they are *"established at `GATE` and carried down every rung"*.
    """
    assert set(TERMINAL_RUNGS) == {Rung.DEGRADE, Rung.ENRICH}
    assert Rung.GATE not in TERMINAL_RUNGS
    assert Rung.DECODE not in TERMINAL_RUNGS


def test_lanes_is_derived_from_the_enum_and_not_a_second_declaration() -> None:
    """INV-21. `Lane`'s own docstring prescribes this expression; the test pins it to the source.

    If someone writes the eleven tokens out here, `enum_val` keeps storing `Lane`'s ordinals and
    the two spellings drift silently -- which is not a rename but two installs disagreeing about
    what the integer in the column means.
    """
    assert set(LANES) == {member.value for member in Lane}
    assert len(LANES) == 11


def test_parse_lanes_is_a_subset_of_lanes_and_is_the_five_of_section_3_1() -> None:
    """The other six are 06's graph lanes and never reach a parse rung."""
    assert set(PARSE_LANES) == {"text", "table", "math", "fields", "caption"}
    assert PARSE_LANES < LANES
    graph_lanes = LANES - PARSE_LANES
    assert set(graph_lanes) == {"anchor", "xref", "entity", "claim", "community", "summary"}


@pytest.mark.parametrize("name", ["GATE", "DECODE", "REPAIR", "PAGE", "REGEN", "DEGRADE", "ENRICH"])
def test_every_rung_round_trips_through_its_name(name: str) -> None:
    """`Rung[name].name == name`, which is the round trip a `signals.toml` and a policy file use.

    `str(member)` is NOT that round trip on an `IntEnum` -- it renders the integer -- so a test
    that used it would pass while a loader spelling `str(rung)` into a stored row wrote `'1'`.
    """
    assert RUNG_BY_NAME[name].name == name
    assert str(int(RUNG_BY_NAME[name])) == str(RUNG_BY_NAME[name].value)
