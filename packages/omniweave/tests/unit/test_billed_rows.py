"""Each eligible Segment's route_decision and its `seg:` work row. **D715.**

Over a store a real ingest wrote, with `derive.entity.llm` on the plan: the rows 05:1103 writes
*"BEFORE anything runs"*, one decision and one `billed_api` row per Segment the selector hands over.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.route.ledger import read_set_from
from omniweave.route.rung import Rung
from omniweave.run.dispatch import dispatch_key
from omniweave.run.operators.billed import (
    COVERED_KEY,
    FLOOR_KEY,
    RULE_ID,
    RULE_ORIGIN,
    enqueue_billed,
)
from omniweave.run.operators.derive import DerivePlan
from omniweave.run.routing import INGEST_HINTS_DIGEST
from omniweave_core.discovery import catalog
from test_billed_selector import LLM, _policy
from test_graph_plan import _cover, _ingested, _run_of
from test_graph_residue import _store
from test_run_derive import _ctx

if TYPE_CHECKING:
    from pathlib import Path

ROWS = (
    "SELECT w.unit_uri, w.unit_part, w.operator, w.cost_class, w.status, w.priority, w.driver,"
    " w.dispatch_key, w.service, d.lane, d.rung, d.rule_id, d.rule_origin, d.cause, d.cost_class,"
    " d.admission, d.est_spend, d.generation, d.content_sha256, d.hints_digest, d.decision_id,"
    " d.evidence_digest FROM work AS w JOIN route_decision AS d ON d.decision_id = w.decision_id"
    " WHERE w.cost_class = 'billed_api' ORDER BY w.unit_part"
)


@pytest.fixture(scope="module")
def contract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("rows"))


@pytest.fixture(scope="module")
def plan(tmp_path_factory: pytest.TempPathFactory) -> DerivePlan:
    policy = _policy(tmp_path_factory.mktemp("policy"), enabled=True, billed=True)
    derives, why = DerivePlan.of(catalog(), policy, _ctx(), enable=(LLM,))
    assert derives is not None and [c.card.identity.id for c in derives.billed] == [LLM], why
    return derives


def _parts(connection: sqlite3.Connection) -> list[str]:
    return [
        f"seg:{bytes(c).hex()[:16]}"
        for (c,) in connection.execute(
            "SELECT s.content_digest FROM segment AS s"
            " JOIN doc AS d ON d.doc_ord = s.doc_ord AND d.gen = s.gen"
            " WHERE s.state = 0 AND s.layer = 0 ORDER BY s.segment_id"
        )
    ]


def test_each_segment_handed_over_gets_one_decision_and_one_billed_row(
    contract: Path, plan: DerivePlan
) -> None:
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        parts = _parts(connection)
        queued = enqueue_billed(connection, plan, floor=0.6, now_ms=7)
        assert (queued.documents[LLM], queued.eligible[LLM], queued.queued[LLM]) == (
            1,
            len(parts),
            len(parts),
        )
        rows = connection.execute(ROWS).fetchall()
        assert sorted(r[1] for r in rows) == sorted(parts)
        [candidate] = plan.billed
        [(uri, sha)] = connection.execute(
            "SELECT unit_uri, content_sha256 FROM unit WHERE unit_uri LIKE '%contract.md'"
        ).fetchall()
        expected_key = dispatch_key(LLM, candidate.config_digest, str(candidate.isolation_granted))
        for row in rows:
            assert row[0] == uri and row[2:9] == (
                LLM, "billed_api", "pending", 100, LLM, expected_key, "llm",
            )  # fmt: skip
            assert row[9:16] == (
                "entity", int(Rung.ENRICH), RULE_ID, RULE_ORIGIN,
                f"{COVERED_KEY}=0.00<0.60", "billed_api", "admitted",
            )  # fmt: skip
            spend = json.loads(row[16])
            assert (spend["tokens_in"], spend["tokens_out"], spend["calls"]) == (3989, 806, 1)
            assert (row[17], row[18], row[19]) == (3, sha, INGEST_HINTS_DIGEST)
            [(payload,)] = connection.execute(
                "SELECT payload FROM route_evidence WHERE evidence_digest = ?", (row[21],)
            ).fetchall()
            assert read_set_from(bytes(payload)) == {COVERED_KEY: 0.0, FLOOR_KEY: 0.6}
            assert connection.execute(
                "SELECT decision_id FROM route_unit_decision"
                " WHERE unit_uri = ? AND unit_part = ? AND lane = 'entity'",
                (uri, row[1]),
            ).fetchall() == [(row[20],)]
    finally:
        connection.rollback()
        connection.close()


def test_a_second_enqueue_writes_nothing_and_the_decisions_converge(
    contract: Path, plan: DerivePlan
) -> None:
    """Ruling 5: `route_decision_identity` and `work_identity` hold."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        first = enqueue_billed(connection, plan, floor=0.6, now_ms=7)
        counts = "SELECT (SELECT count(*) FROM route_decision), (SELECT count(*) FROM work)"
        before = connection.execute(counts).fetchone()
        again = enqueue_billed(connection, plan, floor=0.6, now_ms=8)
        assert (again.eligible[LLM], again.queued[LLM]) == (first.eligible[LLM], 0)
        assert connection.execute(counts).fetchone() == before
    finally:
        connection.rollback()
        connection.close()


def test_cheaper_cover_decides_which_segments_and_what_each_decision_says(
    contract: Path, plan: DerivePlan
) -> None:
    """A wholly covered Segment gets no row; a half-covered one says so in its cause."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        segments = connection.execute(
            "SELECT s.segment_id, s.n_blocks, s.content_digest FROM segment AS s"
            " JOIN doc AS d ON d.doc_ord = s.doc_ord AND d.gen = s.gen"
            " WHERE s.state = 0 ORDER BY s.n_blocks DESC"
        ).fetchall()
        (half, n, half_digest), (whole, m, whole_digest) = segments[0], segments[1]
        assert n % 2 == 0 or n >= 3, "a half under 0.6"
        free = _run_of(connection, 0, 20)
        _cover(connection, half, free, range(n // 2))
        _cover(connection, whole, free, range(m))
        enqueue_billed(connection, plan, floor=0.6, now_ms=7)
        causes = dict(
            connection.execute(
                "SELECT w.unit_part, d.cause FROM work AS w"
                " JOIN route_decision AS d ON d.decision_id = w.decision_id"
                " WHERE w.cost_class = 'billed_api'"
            ).fetchall()
        )
        assert f"seg:{bytes(whole_digest).hex()[:16]}" not in causes
        assert causes[f"seg:{bytes(half_digest).hex()[:16]}"] == (
            f"{COVERED_KEY}={(n // 2) / n:.2f}<0.60"
        )
    finally:
        connection.rollback()
        connection.close()


def test_a_plan_with_no_billed_pass_writes_nothing(contract: Path, plan: DerivePlan) -> None:
    from dataclasses import replace  # noqa: PLC0415

    connection = sqlite3.connect(_store(contract))
    try:
        queued = enqueue_billed(connection, replace(plan, billed=()), floor=0.6, now_ms=7)
        assert (sum(queued.eligible.values()), sum(queued.queued.values())) == (0, 0)
        assert connection.execute(
            "SELECT count(*) FROM work WHERE cost_class = 'billed_api'"
        ).fetchone() == (0,)
    finally:
        connection.rollback()
        connection.close()


def test_a_floor_of_zero_hands_nothing_over(contract: Path, plan: DerivePlan) -> None:
    """06:2629: a Segment is handed over when its cover is BELOW the floor; nothing is below 0."""
    connection = sqlite3.connect(_store(contract))
    try:
        queued: Any = enqueue_billed(connection, plan, floor=0.0, now_ms=7)
        assert (queued.documents[LLM], queued.eligible[LLM]) == (0, 0)
    finally:
        connection.rollback()
        connection.close()


def test_a_document_whose_segmentation_has_not_settled_is_not_in_scope(
    contract: Path, plan: DerivePlan
) -> None:
    """Ruling 6: the document's `derive.segment` row is `done` before its Segments are decided."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        connection.execute("UPDATE work SET status = 'claimed' WHERE operator = 'derive.segment'")
        queued = enqueue_billed(connection, plan, floor=0.6, now_ms=7)
        assert (queued.documents[LLM], queued.eligible[LLM]) == (0, 0)
    finally:
        connection.rollback()
        connection.close()
