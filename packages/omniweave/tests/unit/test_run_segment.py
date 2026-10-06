"""`run/operators/segment.py` without a worker: the plan, the row, the ledger, the report.

The whole path -- a real `ow add`, a real worker, the rows verified -- is
`tests/conform/test_segments_at_ingest.py`. D665.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the enqueue statement runs against a real store.
from pathlib import Path
from typing import Any, cast

import pytest
from omniweave.run.dispatch import dispatch_key
from omniweave.run.operators.parse import ParseLedger, ParseTally
from omniweave.run.operators.segment import (
    SEGMENT_OPERATOR,
    SEGMENT_PRIORITY,
    SEGMENTER_ID,
    SegmentPlan,
)
from omniweave.run.routing import resolve_policy
from omniweave_core.config import load
from omniweave_core.discovery import catalog
from omniweave_core.operator import Outcome, Roots, RunContext
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_ports.types import UnitRef

UNIT = UnitRef(uri="file:///docs/a.md", part="", content_sha256="ab" * 32, byte_len=10)
OPEN = "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"


def _ctx() -> RunContext:
    return RunContext(
        run_id="r_0000000000000000000000000",
        generation=3,
        trigger="cli",
        roots=Roots(source=Path(), output=Path(), cache=Path()),
        config_digest="c" * 64,
        semantic_digest="s" * 64,
        policy_digest="p" * 64,
        pricebook_digest="b" * 64,
        catalog_digest="k" * 64,
        limits=cast("Any", object()),
        admission=cast("Any", object()),
        services=cast("Any", object()),
        budget=cast("Any", object()),
        cancel=cast("Any", object()),
        clock=cast("Any", object()),
        events=cast("Any", object()),
    )


def _plan(tmp_path: Path, body: str = OPEN) -> tuple[SegmentPlan | None, str]:
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    policy = resolve_policy(load(cwd=tmp_path, env={}))
    return SegmentPlan.of(catalog(), policy, _ctx())


def test_the_plan_is_the_resolved_candidate_for_the_pinned_segmenter(tmp_path: Path) -> None:
    plan, why = _plan(tmp_path)
    assert plan is not None, why
    assert why == ""
    assert plan.candidate.card.identity.id == SEGMENTER_ID
    assert dict(plan.candidate.effective_config)["target_tokens"] == 1200


def test_a_segmenter_resolve_refuses_is_no_plan_and_a_reason_why(tmp_path: Path) -> None:
    """The shipped `require_lock = true` with no lockfile: no row, and the report can say why."""
    plan, why = _plan(tmp_path, "[drivers]\nallow_unattested = true\n")
    assert plan is None
    assert why.startswith("not_in_lockfile"), why


def test_the_enqueued_row_is_a_free_derive_row_with_a_driver_and_no_decision(
    tmp_path: Path,
) -> None:
    """D665's row, written by the statement into a real store whose CHECKs judge it."""
    plan, _ = _plan(tmp_path)
    assert plan is not None
    statement = plan.statement(UNIT)
    params = dict(statement.params)
    candidate = plan.candidate
    assert params["operator"] == SEGMENT_OPERATOR
    assert params["driver"] == SEGMENTER_ID
    assert params["priority"] == SEGMENT_PRIORITY
    assert params["dispatch_key"] == dispatch_key(
        SEGMENTER_ID, candidate.config_digest, str(candidate.isolation_granted)
    )
    store = tmp_path / "s.owstore"
    connection = ow.connect(store)
    try:
        migrate.apply_pending(connection, now_ns=1)
        connection.execute(
            "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen) "
            "VALUES(?, 'settled', 'internal', 1)",
            (UNIT.uri,),
        )
        connection.execute(statement.sql, params)
        connection.execute(statement.sql, params)  # a resumed run enqueues nothing twice
    finally:
        connection.close()
    raw = sqlite3.connect(store)
    try:
        rows = raw.execute(
            "SELECT operator, driver, decision_id, cost_class, status, unit_part FROM work"
        ).fetchall()
    finally:
        raw.close()
    assert rows == [(SEGMENT_OPERATOR, SEGMENTER_ID, None, "free", "pending", "")]


class _View:
    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.failure_class = "corrupt_input"


@pytest.mark.parametrize(
    ("outcome", "names"),
    [
        (Outcome.OK, ["unit_settled", "segment_enqueued"]),
        (Outcome.OK_PARTIAL, ["unit_settled", "segment_enqueued"]),
        (Outcome.FAILED_PERMANENT, ["unit_parse_failed"]),
        (Outcome.FAILED_TRANSIENT, []),
    ],
)
def test_the_segment_row_rides_only_a_settled_parse(
    tmp_path: Path, outcome: Outcome, names: list[str]
) -> None:
    plan, _ = _plan(tmp_path)
    assert plan is not None
    ledger = ParseLedger()
    ledger.record(1, UNIT.uri, 3, plan.statement(UNIT))
    assert [s.name for s in ledger(1, cast("Any", _View(outcome)))] == names
    ledger.forget(1)
    assert ledger(1, cast("Any", _View(Outcome.OK))) == ()
    ledger.record(1, UNIT.uri, 4)  # a row id reused after forget() carries no stale follow-on
    expected = ["unit_settled"] if outcome in (Outcome.OK, Outcome.OK_PARTIAL) else names
    assert [s.name for s in ledger(1, cast("Any", _View(outcome)))] == expected


def test_the_report_says_what_segmenting_did_and_why_it_did_not() -> None:
    tally = ParseTally()
    tally.parsed["parse.text.builtin"] = 2
    tally.segmented = 2
    tally.segments_created, tally.segments_kept, tally.segments_retired = 5, 1, 1
    tally.segment_failed["empty_result"] = 1
    lines = tally.lines()
    assert "  segment   2 document(s): 5 Segment(s) written, 1 kept, 1 retired" in lines
    assert "  segment   1 failed (empty_result 1)" in lines
    quiet = ParseTally()
    quiet.parsed["parse.text.builtin"] = 1
    quiet.segment_skipped = "not_in_lockfile: no row"
    assert "  segment   none enqueued: not_in_lockfile: no row" in quiet.lines()
