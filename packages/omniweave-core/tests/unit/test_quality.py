"""`omniweave_core.quality` -- the six values, the two that may never be accuracy, and the gap.

Three of these tests read `_plan/` and one reads the committed DDL, because every constant in this
module is a transcription of something the framework already states somewhere else: a vocabulary
retyped by hand is a vocabulary that drifts, and the drift is silent until a column is populated by
a `TruthKind` that should never have reached it.

The one test that asserts an ABSENCE is `test_audit_and_feedback_have_no_truth_kind`. It pins D232
rather than a behaviour: `audit`'s reference is a second driver, which is the same shape the plan
calls `agreement`, and no document assigns it a value. The `None` is the finding, and a later plan
edit that fills the gap should fail this test rather than pass it quietly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from omniweave_core import quality as q
from omniweave_core.errors import QualityError

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import PlanDocs


# ---------------------------------------------------------------------------
# The two vocabularies, against the documents that fix them
# ---------------------------------------------------------------------------


def test_the_six_truth_kinds_are_the_glossarys_six_in_its_order(plan: PlanDocs) -> None:
    """glossary.md:1094 states the enum as one `|`-separated sentence."""
    plan.require()
    hits = plan.grep(r"^\| `TruthKind` \| enum \|", documents=("glossary.md",))
    assert len(hits) == 1
    enum = hits[0].text.split("reference:")[1].split(".")[0]
    stated = tuple(part.strip(" `") for part in enum.split(r"\|"))
    assert stated == q.TRUTH_KINDS


def test_the_four_sources_are_the_ddls_check_in_the_ddls_order(migrations: Path) -> None:
    """`route_quality.source`'s CHECK is the closed set, and this is where it is closed."""
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    found = re.search(r"source TEXT NOT NULL CHECK \(source IN \(([^)]*)\)\)", ddl)
    assert found is not None
    assert tuple(re.findall(r"'([a-z]+)'", found.group(1))) == q.QUALITY_SOURCES


def test_agreement_and_self_are_the_two_that_may_never_be_accuracy(plan: PlanDocs) -> None:
    """13:1230, and four other documents say it in the same words."""
    plan.require()
    hits = plan.grep(r"may \*\*never\*\* populate an accuracy column")
    assert len(hits) >= 4
    assert set(q.NEVER_ACCURACY) == {"agreement", "self"}


def test_self_is_narrower_than_never_accuracy_because_the_view_already_excludes_it() -> None:
    """`NEVER_SCORED` is a subset, not a synonym: `agree` rows DO enter the scoreboard."""
    assert q.NEVER_SCORED < q.NEVER_ACCURACY
    assert q.AGREEMENT not in q.NEVER_SCORED


# ---------------------------------------------------------------------------
# The join between them, and the hole in it
# ---------------------------------------------------------------------------


def test_agree_maps_to_agreement_and_self_maps_to_self() -> None:
    assert q.truth_kind_of("agree") == q.AGREEMENT
    assert q.truth_kind_of("self") == q.SELF


def test_audit_and_feedback_have_no_truth_kind() -> None:
    """D232. `None` is "the plan states none", never "not applicable" and never a default."""
    assert q.truth_kind_of("audit") is None
    assert q.truth_kind_of("feedback") is None


def test_a_source_outside_the_check_raises_rather_than_returning_none() -> None:
    """Two different unknowns: a source the CHECK admits with no stated kind, and a bad source."""
    with pytest.raises(QualityError) as caught:
        q.truth_kind_of("vibes")
    assert "not a route_quality.source" in str(caught.value)
    assert caught.value.fix


# ---------------------------------------------------------------------------
# The admissibility rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["human", "rendered", "synth_ocr"])
def test_the_three_admissible_kinds_carry_no_reason(kind: str) -> None:
    assert q.why_not_accuracy(kind) == ""
    q.check_accuracy_column("structure_f1", kind)


@pytest.mark.parametrize("kind", ["agreement", "self", "native_run"])
def test_the_three_inadmissible_kinds_each_carry_their_own_reason(kind: str) -> None:
    """Three different reasons and not one message with a substitution: 13:37's failure mode is
    that the number *measures self-consistency*, and which kind of self-consistency differs."""
    why = q.why_not_accuracy(kind)
    assert why
    assert why != q.why_not_accuracy("agreement") or kind == "agreement"


def test_the_agreement_reason_names_the_column_heading_the_plan_prints() -> None:
    assert '"Agreement (not accuracy)"' in q.why_not_accuracy("agreement")


def test_an_unknown_truth_kind_is_refused_and_lists_the_six() -> None:
    why = q.why_not_accuracy("vibes")
    assert "not a TruthKind" in why
    for kind in q.TRUTH_KINDS:
        assert kind in why


def test_check_accuracy_column_raises_with_a_fix_and_names_the_metric() -> None:
    with pytest.raises(QualityError) as caught:
        q.check_accuracy_column("structure_f1", q.AGREEMENT)
    assert "structure_f1" in str(caught.value)
    assert caught.value.fix
    assert caught.value.code() == "OW_QUALITY"


# ---------------------------------------------------------------------------
# F23, which is open
# ---------------------------------------------------------------------------


def test_only_audit_may_demote() -> None:
    """12:1103 while F23 is open, and `agree` is the source the restriction is aimed at."""
    assert q.may_demote("audit")
    assert not any(q.may_demote(other) for other in q.QUALITY_SOURCES if other != "audit")


def test_the_demotion_rule_is_stated_over_a_source_because_audit_has_no_truth_kind() -> None:
    """The two halves of D232 in one assertion: the one source that may demote is the one the
    reference vocabulary cannot name, so a rule phrased over `TruthKind` would be unanswerable."""
    assert q.may_demote("audit")
    assert q.truth_kind_of("audit") is None
