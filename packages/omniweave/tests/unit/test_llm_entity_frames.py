"""`derive.entity.llm`'s frames through the host (D710): decoded, driven, and judged by the sink."""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.model.enums import Method
from omniweave_core.store.graph import PassIdentity
from omniweave_core.store.items import BilledLane, build_segment_view, decode_items, drive_items
from omniweave_llm.entity import answer_frames, unparsed_frames
from omniweave_llm.view import read_views
from test_billed_view import _NoSpend
from test_graph_decide import _ingested, _store
from test_graph_plan import _cover, _run_of

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("llm_frames"))


def _identity(connection: sqlite3.Connection) -> PassIdentity:
    [(producer,)] = connection.execute("SELECT min(producer_id) FROM producer").fetchall()
    return PassIdentity(
        pass_id="derive.entity.llm",  # noqa: S106 -- a DriverId, not a credential.
        producer_id=int(producer),
        method=Method.LLM,
        origin_operator="op.derive",
        origin_driver="derive.entity.llm",
        driver_schema_v=1,
        cost_class="billed_api",
    )


def _codes(connection: sqlite3.Connection, run_id: int) -> dict[str, int]:
    return dict(
        connection.execute(
            "SELECT code, count(*) FROM quarantine WHERE run_id = ? GROUP BY code", (run_id,)
        ).fetchall()
    )


def _land(connection: sqlite3.Connection, item_view: Any, frames: list[dict[str, Any]]) -> Any:
    body = b"".join(json.dumps(f).encode() + b"\n" for f in frames)
    [unit] = decode_items(body, [item_view])
    return drive_items(connection, unit, _identity(connection), _NoSpend())


def test_an_answer_lands_and_the_sink_judges_each_item(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        [(segment, n)] = connection.execute(
            "SELECT segment_id, n_blocks FROM segment WHERE state = 0"
            " ORDER BY n_blocks DESC LIMIT 1"
        ).fetchall()
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        item_view = build_segment_view(
            connection, int(segment), billed=BilledLane("entity", (2, 10))
        )
        [view] = read_views(item_view.body)
        by_text = {b.text: b for b in view.blocks if b.text}
        acme, beta, gamma = by_text["Acme Holdings"], by_text["Beta Corp"], by_text["Gamma Inc"]
        _cover(connection, int(segment), _run_of(connection, 0, 20), [
            ordinal for ordinal, frame in enumerate(view.blocks) if frame.cite == gamma.cite
        ])  # fmt: skip
        item_view = build_segment_view(
            connection, int(segment), billed=BilledLane("entity", (2, 10))
        )
        [view] = read_views(item_view.body)
        assert [b.covered for b in view.blocks if b.cite == gamma.cite] == [True]
        answer = {
            "entities": [
                {"name": "Acme Holdings", "etype": "org", "cite": acme.cite,
                 "quote": "Acme Holdings", "description": None},
                {"name": "Beta Corp", "etype": "org", "cite": beta.cite, "quote": "Beta Corp",
                 "description": None},
                {"name": "Gamma Inc", "etype": "org", "cite": gamma.cite, "quote": "Gamma Inc",
                 "description": None},
                {"name": "Omega", "etype": "org", "cite": beta.cite, "quote": "Omega Trust",
                 "description": None},
            ],
            "relations": [
                {"source": "Acme Holdings", "target": "Beta Corp", "relation": "party_to",
                 "cite": acme.cite, "quote": "Acme Holdings"},
                {"source": "Acme Holdings", "target": "Zeta", "relation": "party_to",
                 "cite": acme.cite, "quote": "Acme Holdings"},
            ],
            "more_available": False,
        }  # fmt: skip
        report = _land(connection, item_view, answer_frames(view, answer))
        codes = _codes(connection, report.run_id)
        assert codes.pop("OW_GRAPH_COVERED_GROUND") == 1, "Gamma's block was covered"
        assert codes.pop("OW_GRAPH_UNGROUNDED") == 1, "'Omega Trust' is not in Beta's block"
        assert codes.pop("OW_GRAPH_UNPARSED_ITEM") == 1, "the relation to Zeta, kept"
        assert codes.pop("OW_GRAPH_TRUST_CLAMPED") >= 1, "extracted claimed, inferred written"
        assert codes == {}
        mentions = connection.execute(
            "SELECT m.trust, b.cite FROM mention AS m JOIN block AS b USING (block_id)"
            " WHERE m.run_id = ? ORDER BY b.cite",
            (report.run_id,),
        ).fetchall()
        assert mentions == sorted([(1, acme.cite), (1, beta.cite)], key=lambda r: r[1])
        assert connection.execute(
            "SELECT count(*), max(trust) FROM edge WHERE run_id = ?", (report.run_id,)
        ).fetchone() == (1, 1)
        [(cover,)] = connection.execute(
            "SELECT n_covered FROM derive_cover WHERE run_id = ? AND lane = 'entity'",
            (report.run_id,),
        ).fetchall()
        assert cover == 2, "Acme's and Beta's blocks, not Gamma's"
        assert n >= 4
    finally:
        connection.rollback()
        connection.close()


def test_an_unparsed_answer_is_kept_whole(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        [(segment,)] = connection.execute(
            "SELECT segment_id FROM segment WHERE state = 0 ORDER BY n_blocks DESC LIMIT 1"
        ).fetchall()
        item_view = build_segment_view(
            connection, int(segment), billed=BilledLane("entity", (2, 10))
        )
        [view] = read_views(item_view.body)
        report = _land(connection, item_view, unparsed_frames(view, "{ not json", ["$: not JSON"]))
        [(payload,)] = connection.execute(
            "SELECT payload FROM quarantine WHERE run_id = ? AND code = 'OW_GRAPH_UNPARSED_ITEM'",
            (report.run_id,),
        ).fetchall()
        assert json.loads(payload)["unparsed"] == "{ not json"
        [(reason,)] = connection.execute(
            "SELECT empty_reason FROM derive_cover WHERE run_id = ?", (report.run_id,)
        ).fetchall()
        assert "did not parse" in reason
    finally:
        connection.rollback()
        connection.close()
