"""`derive.claim.llm`'s frames through the host (D721): decoded, driven, and judged by the sink."""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.model.enums import Method
from omniweave_core.store.graph import PassIdentity
from omniweave_core.store.items import BilledLane, build_segment_view, decode_items, drive_items
from omniweave_llm.claim import answer_frames, unparsed_frames
from omniweave_llm.view import read_views
from test_billed_view import _NoSpend
from test_graph_decide import _ingested, _store
from test_graph_plan import _cover, _run_of

if TYPE_CHECKING:
    from pathlib import Path

CLAIM_LLM = (2, 20)


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("llm_claims"))


def _identity(connection: sqlite3.Connection) -> PassIdentity:
    [(producer,)] = connection.execute("SELECT min(producer_id) FROM producer").fetchall()
    return PassIdentity(
        pass_id="derive.claim.llm",  # noqa: S106 -- a DriverId, not a credential.
        producer_id=int(producer),
        method=Method.LLM,
        origin_operator="op.derive",
        origin_driver="derive.claim.llm",
        driver_schema_v=1,
        cost_class="billed_api",
    )


def _land(connection: sqlite3.Connection, item_view: Any, frames: list[dict[str, Any]]) -> Any:
    body = b"".join(json.dumps(f).encode() + b"\n" for f in frames)
    [unit] = decode_items(body, [item_view])
    return drive_items(connection, unit, _identity(connection), _NoSpend())


def _codes(connection: sqlite3.Connection, run_id: int) -> dict[str, int]:
    return dict(
        connection.execute(
            "SELECT code, count(*) FROM quarantine WHERE run_id = ? GROUP BY code", (run_id,)
        ).fetchall()
    )


def _segment_view(connection: sqlite3.Connection) -> tuple[int, Any, Any]:
    [(segment,)] = connection.execute(
        "SELECT segment_id FROM segment WHERE state = 0 ORDER BY n_blocks DESC LIMIT 1"
    ).fetchall()
    item_view = build_segment_view(connection, int(segment), billed=BilledLane("claim", CLAIM_LLM))
    [view] = read_views(item_view.body)
    return int(segment), item_view, view


def test_claims_land_on_their_subjects_and_the_sink_judges_each(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'claim'")
        segment, item_view, view = _segment_view(connection)
        by_text = {b.text: b for b in view.blocks if b.text}
        acme, beta, gamma = by_text["Acme Holdings"], by_text["Beta Corp"], by_text["Gamma Inc"]
        _cover(connection, segment, _run_of(connection, 0, 20), [
            ordinal for ordinal, block in enumerate(view.blocks) if block.cite == gamma.cite
        ])  # fmt: skip
        connection.execute(
            "UPDATE derive_cover SET lane = 'claim' WHERE segment_id = ? AND lane = 'entity'"
            " AND run_id = (SELECT max(run_id) FROM derive_run)",
            (segment,),
        )
        item_view = build_segment_view(connection, segment, billed=BilledLane("claim", CLAIM_LLM))
        [view] = read_views(item_view.body)
        answer = {
            "claims": [
                {"subject": "Acme Holdings", "subject_etype": "org", "claim_type": "attribute",
                 "predicate": "role", "object": "Seller", "object_is_entity": False,
                 "status": "asserted", "t_start": "2026-06", "t_end": None, "description": None,
                 "cite": acme.cite, "quote": "Acme Holdings"},
                {"subject": "Beta Corp", "subject_etype": "org", "claim_type": "attribute",
                 "predicate": "counterparty", "object": "Acme Holdings", "object_is_entity": True,
                 "status": "asserted", "t_start": None, "t_end": None, "description": None,
                 "cite": beta.cite, "quote": "Beta Corp"},
                {"subject": "Gamma Inc", "subject_etype": "org", "claim_type": "attribute",
                 "predicate": "role", "object": "Agent", "object_is_entity": False,
                 "status": "asserted", "t_start": None, "t_end": None, "description": None,
                 "cite": gamma.cite, "quote": "Gamma Inc"},
                {"subject": "Beta Corp", "subject_etype": "org", "claim_type": "attribute",
                 "predicate": "role", "object": "Buyer", "object_is_entity": False,
                 "status": "asserted", "t_start": None, "t_end": None, "description": None,
                 "cite": beta.cite, "quote": "Omega Trust"},
            ],
            "more_available": False,
        }  # fmt: skip
        report = _land(connection, item_view, answer_frames(view, answer))
        codes = _codes(connection, report.run_id)
        assert codes.pop("OW_GRAPH_COVERED_GROUND") == 1, "Gamma's block was covered"
        assert codes.pop("OW_GRAPH_UNGROUNDED") == 1, "'Omega Trust' is not in Beta's block"
        assert codes.pop("OW_GRAPH_TRUST_CLAMPED") >= 1, "extracted claimed, inferred written"
        assert codes == {}
        claims = connection.execute(
            "SELECT s.key, c.predicate, c.object_literal, o.key, c.t_start, c.t_precision,"
            " c.status FROM claim AS c JOIN entity AS s ON s.entity_id = c.subject_entity"
            " LEFT JOIN entity AS o ON o.entity_id = c.object_entity WHERE c.run_id = ?"
            " ORDER BY s.key, c.predicate",
            (report.run_id,),
        ).fetchall()
        assert claims == [
            ("acme_holdings", "role", "Seller", None, "2026-06", "month", "asserted"),
            ("beta_corp", "counterparty", None, "acme_holdings", None, None, "asserted"),
        ], claims
        [(cover,)] = connection.execute(
            "SELECT n_covered FROM derive_cover WHERE run_id = ? AND lane = 'claim'",
            (report.run_id,),
        ).fetchall()
        assert cover == 2, "Acme's and Beta's blocks, not Gamma's"
    finally:
        connection.rollback()
        connection.close()


def test_an_unparsed_claim_answer_is_kept_whole(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        _segment, item_view, view = _segment_view(connection)
        report = _land(connection, item_view, unparsed_frames(view, "{ not json", ["$: not JSON"]))
        [(payload,)] = connection.execute(
            "SELECT payload FROM quarantine WHERE run_id = ? AND code = 'OW_GRAPH_UNPARSED_ITEM'",
            (report.run_id,),
        ).fetchall()
        assert json.loads(payload)["unparsed"] == "{ not json"
        [(reason,)] = connection.execute(
            "SELECT empty_reason FROM derive_cover WHERE run_id = ? AND lane = 'claim'",
            (report.run_id,),
        ).fetchall()
        assert "did not parse" in reason
    finally:
        connection.rollback()
        connection.close()
