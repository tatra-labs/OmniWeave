"""`omniweave_core.out.plan`: the roster, the Plan and the total classifier (OUT8).

09-generation.md section 3.7 (`OutUnit` and `Plan`, field by field, and the four decisions), section
5.5 (the seven outcomes in the classifier's order) and section 9 (`ManualReason`). Every outcome is
reached here, each refusal is `OW-T-005`, and the sum is asserted over the outcomes.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.model.block import Cite
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.plan import (
    Classified,
    ManualReason,
    OutUnit,
    Plan,
    UnitOutcome,
    classify_and_assert,
)

BRIEF = parse_brief(
    f"""{BRIEF_SCHEMA}
## canvas
- format: 16:9
- unit: slide
## communication
- primary_language: en-GB
## direction
## density
- per_unit: light
## motion
- level: static
## typography
## rhythm
- u01: {{ anchor: cover }}
## forbidden
""",
    baseline=(),
)
DIGEST = "sha256:" + "0" * 64


def _unit(n: int, **fields: Any) -> OutUnit:
    base: dict[str, Any] = {
        "id": f"u{n:02d}",
        "ord": n,
        "il_path": f"il/u{n:02d}.svg",
        "nsig": f"{n:08x}",
    }
    base.update(fields)
    return OutUnit(**base)


def _plan(*units: OutUnit, **fields: Any) -> Plan:
    roster = units or (_unit(1), _unit(2))
    base: dict[str, Any] = {
        "schema": "omniweave.out-plan/1",
        "target": "pptx",
        "slug": "q3-board",
        "artifact_gen": 1,
        "delivery": "release",
        "units": roster,
        "unit_count": len(roster),
        "brief": BRIEF,
        "corpus": "c1",
        "cites": {Cite("d7#412"): 3},
        "gate_status": GateStatus.PASSED,
        "il_digest": DIGEST,
        "constructs_digest": DIGEST,
        "ledger_digest": DIGEST,
        "brief_digest": BRIEF.digest(),
        "card_sha256": "0" * 64,
    }
    base.update(fields)
    return Plan(**base)


def _classify(
    plan: Plan, *, baked: dict[str, str] | None = None, visual: bool = True
) -> dict[str, Classified]:
    return classify_and_assert(plan, baked=baked or {}, visual_changed=lambda _: visual)


# ---------------------------------------------------------------------------
# OutUnit and Plan, ruling 1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"id": "u1"}, "does not match"),
        ({"id": "slide1"}, "does not match"),
        ({"ord": 0}, "below 1"),
        ({"il_path": "u01.svg"}, "under il/"),
        ({"source_nsig": "00000001"}, "without a source_part"),
        ({"source_ord": 1}, "without a source_part"),
    ],
)
def test_an_out_unit_refuses_a_malformed_shape(fields: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _unit(1, **fields)


def test_an_out_unit_takes_its_anchor_from_the_brief() -> None:
    unit = _unit(1, anchor=BRIEF.anchor("u01"))
    assert unit.anchor == "cover"
    assert (
        _unit(
            1, source_part="ppt/slides/slide1.xml", source_nsig="00000001", source_ord=1
        ).source_ord
        == 1
    )


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"schema": "omniweave.out-plan/2"}, "schema"),
        ({"delivery": "final"}, "release or draft"),
        ({"artifact_gen": 0}, "below 1"),
        ({"unit_count": 3}, "unit_count"),
        ({"units": (_unit(1), _unit(3, ord=3))}, "1..2"),
        ({"units": (_unit(2, ord=2), _unit(1, ord=1))}, "1..2"),
        ({"units": (_unit(1), _unit(1, ord=2))}, "repeat"),
    ],
)
def test_a_plan_refuses_a_malformed_roster(fields: dict[str, Any], match: str) -> None:
    if "units" in fields and "unit_count" not in fields:
        fields["unit_count"] = len(fields["units"])
    with pytest.raises(ValueError, match=match):
        _plan(**fields)


# ---------------------------------------------------------------------------
# The classifier: 09 section 5.5, in order (rulings 2-5)
# ---------------------------------------------------------------------------

EDITED = {"source_part": "ppt/slides/slide1.xml", "source_nsig": "00000001", "source_ord": 1}


def test_each_of_the_seven_outcomes_in_the_classifiers_order() -> None:
    plan = _plan(
        _unit(1, manual_reason=ManualReason.UNVERIFIABLE_DATA, **EDITED),
        _unit(2),
        _unit(3),
        _unit(
            4,
            nsig="00000001",
            source_part="ppt/slides/slide4.xml",
            source_nsig="00000001",
            source_ord=4,
        ),
        _unit(
            5,
            nsig="00000001",
            source_part="ppt/slides/slide1.xml",
            source_nsig="00000001",
            source_ord=1,
        ),
        _unit(6, source_part="ppt/slides/slide6.xml", source_nsig="ffffffff", source_ord=6),
    )
    out = _classify(plan, baked={"u03": "style.mix-blend-mode at 192 dpi"}, visual=False)
    assert out == {
        "u01": Classified(UnitOutcome.MANUAL_REQUIRED, "unverifiable_data"),
        "u02": Classified(UnitOutcome.NATIVE),
        "u03": Classified(UnitOutcome.BAKED, "style.mix-blend-mode at 192 dpi"),
        "u04": Classified(UnitOutcome.PASSTHROUGH),
        "u05": Classified(UnitOutcome.CLONED_PASSTHROUGH),
        "u06": Classified(UnitOutcome.PATCHED),
    }
    rebuilt = _classify(
        _plan(_unit(1, source_part="p", source_nsig="ffffffff", source_ord=1)), visual=True
    )
    assert rebuilt == {"u01": Classified(UnitOutcome.REBUILT)}


def test_a_bake_on_an_edited_unit_does_not_make_it_baked() -> None:
    """09's `baked` is the create path's: `native | baked (baked iff a bake row fired)`."""
    plan = _plan(_unit(1, nsig="00000001", **EDITED))
    assert _classify(plan, baked={"u01": "x"}) == {"u01": Classified(UnitOutcome.PASSTHROUGH)}


@pytest.mark.parametrize(
    "unit",
    [
        _unit(1, nsig=None),
        _unit(1, nsig=None, **EDITED),
        _unit(1, nsig=None, manual_reason=ManualReason.UNREPRESENTABLE),
        _unit(1, source_part="ppt/slides/slide1.xml"),
    ],
)
def test_a_unit_with_nothing_to_compare_is_unclassifiable(unit: OutUnit) -> None:
    with pytest.raises(TargetError) as caught:
        _classify(_plan(unit))
    assert caught.value.code() == "OW_TARGET_UNIT_UNCLASSIFIED"
    assert caught.value.numeric() == "OW-T-005"


def test_the_sum_is_asserted_over_the_outcomes_and_nothing_is_written() -> None:
    plan = _plan()
    object.__setattr__(plan, "units", (plan.units[0], replace(plan.units[0], ord=2)))
    with pytest.raises(TargetError, match="1 units classified against a roster of 2"):
        _classify(plan)


@pytest.mark.parametrize("outcome", [UnitOutcome.MANUAL_REQUIRED, UnitOutcome.BAKED])
def test_two_outcomes_need_a_reason(outcome: UnitOutcome) -> None:
    with pytest.raises(ValueError, match="needs a reason"):
        Classified(outcome)
    assert Classified(outcome, "r").reason == "r"


def test_the_vocabularies_are_the_charters() -> None:
    assert [o.value for o in UnitOutcome] == [
        "native",
        "baked",
        "passthrough",
        "cloned_passthrough",
        "patched",
        "rebuilt",
        "manual_required",
    ]
    assert len(ManualReason) == 7
