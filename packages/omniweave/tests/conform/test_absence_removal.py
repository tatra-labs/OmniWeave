"""13-quality.md section 8.6's Construction 1, end to end: ground truth by removal. D933.

`omniweave_conform.removal` builds each catalogue corpus twice through a real `ow add`, as
generated and with every removable planted sentence deleted, then asks every question of the
corpus its population names. It spawns workers, so it is the conform tier's by Q-G25's rule.

`false_confident_zero` is the claim held here: no answerable question is answered `absent`.
`absent_recall` is measured and not held, because it is ungated (13:1137).
"""

from __future__ import annotations

from pathlib import Path
from time import time_ns

import pytest
from omniweave_conform.removal import ABSENT, ANSWERABLE, REMOVED, run_suite

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]
STATES = {"ok", "low_confidence", "absent", "degraded"}


def test_no_answerable_question_is_answered_absent(tmp_path: Path) -> None:
    done = run_suite(REPO, work=tmp_path, now_ns=time_ns)
    counts = {p: len(done.of(p)) for p in (ANSWERABLE, REMOVED, ABSENT)}
    assert counts == {ANSWERABLE: 13, REMOVED: 12, ABSENT: 5}
    assert done.shared == ("data-ret-indexed-cap",)
    assert {one.state for one in done.asked} <= STATES
    wrong = [one.question.task_id for one in done.answerable if one.answered_absent]
    assert wrong == [], "false_confident_zero: an answerable question was answered absent"
    assert sorted({path.split("/", 1)[0] for path in done.documents}) == [
        "data_room",
        "data_room-removed",
        "legal_matter",
        "legal_matter-removed",
        "personal_archive",
        "personal_archive-removed",
    ]
