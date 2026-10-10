"""The billed view (D709): vocabularies, `doc`, per-block `covered`, and the covered-ground gate."""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.limits import MAX_SEGMENT_BLOCKS
from omniweave_core.model.block import Cite
from omniweave_core.model.enums import Method, Trust
from omniweave_core.store.graph import (
    OW_GRAPH_COVERED_GROUND,
    EntityDraft,
    MentionDraft,
    PassIdentity,
    SqliteGraphSink,
    TmpRef,
)
from omniweave_core.store.items import BilledLane, ItemView, build_segment_view
from test_graph_decide import _ingested, _store
from test_graph_plan import _cover, _run_of

if TYPE_CHECKING:
    from pathlib import Path

ENTITY_LLM = BilledLane("entity", (2, 10))


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("billed"))


def _frames(view: ItemView) -> list[dict[str, Any]]:
    return [json.loads(line) for line in view.body.decode("utf-8").splitlines()]


def _biggest(connection: sqlite3.Connection) -> tuple[int, int]:
    """The live Segment with the most members, and its member count."""
    [(segment, n)] = connection.execute(
        "SELECT segment_id, n_blocks FROM segment WHERE state = 0 ORDER BY n_blocks DESC LIMIT 1"
    ).fetchall()
    assert int(n) >= 4, "the parties table is one Segment of many members"
    return int(segment), int(n)


def _bits(ords: set[int]) -> bytes:
    value = 0
    for k in ords:
        value |= 1 << (MAX_SEGMENT_BLOCKS - 1 - k)
    return value.to_bytes(MAX_SEGMENT_BLOCKS // 8, "big")


def test_a_free_view_is_the_free_view(parties: Path) -> None:
    """Ruling 6 unchanged: no vocabulary, no `doc`, nothing covered, no bitmap."""
    connection = sqlite3.connect(_store(parties))
    try:
        segment, _ = _biggest(connection)
        view = build_segment_view(connection, segment)
        header, *blocks = _frames(view)
        assert not {"etypes", "relations", "doc"} & set(header)
        assert header["defaults"]["covered"] is False
        assert not any("covered" in b for b in blocks)
        assert view.ref.uncovered is None
    finally:
        connection.close()


def test_the_billed_header_carries_what_a_prompt_renders(parties: Path) -> None:
    """Rulings 8-10: builtin and user types, never proposed, `unknown` last; every relation; doc."""
    connection = sqlite3.connect(_store(parties))
    try:
        for etype, source in [("covenant", "proposed"), ("warrant", "user")]:
            connection.execute(
                "INSERT INTO etype_vocab(etype, scope, resolution, source) VALUES(?, 'corpus',"
                " 'fuzzy', ?)",
                (etype, source),
            )
        segment, _ = _biggest(connection)
        header = _frames(build_segment_view(connection, segment, billed=ENTITY_LLM))[0]
        kept = sorted(
            str(e)
            for (e,) in connection.execute(
                "SELECT etype FROM etype_vocab WHERE source <> 'proposed' AND etype <> 'unknown'"
            )
        )
        assert header["etypes"] == [*kept, "unknown"]
        assert "covenant" not in header["etypes"] and "warrant" in header["etypes"]
        relations = connection.execute(
            "SELECT relation, actor_rule FROM relation_vocab ORDER BY relation"
        ).fetchall()
        assert header["relations"] == [{"relation": r, "actor_rule": a} for r, a in relations]
        assert len(header["relations"]) >= 13, "the thirteen builtins"
        [(fmt, media)] = connection.execute(
            "SELECT format, media_type FROM doc WHERE doc_ord ="
            " (SELECT doc_ord FROM segment WHERE segment_id = ?)",
            (segment,),
        ).fetchall()
        assert header["doc"] == {"format": fmt, "media_type": media}
    finally:
        connection.rollback()
        connection.close()


def test_blocks_are_covered_against_the_cheaper_cover(parties: Path) -> None:
    """Ruling 7: a free run's cover marks blocks; a later billed run's does not; the bitmap is the
    members less the cheaper cover."""
    connection = sqlite3.connect(_store(parties))
    try:
        segment, n = _biggest(connection)
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        _cover(connection, segment, _run_of(connection, 0, 20), [0, 2])
        _cover(connection, segment, _run_of(connection, 2, 20), range(n))
        view = build_segment_view(connection, segment, billed=ENTITY_LLM)
        header, *blocks = _frames(view)
        assert header["defaults"]["covered"] is False
        assert {b["ord"] for b in blocks if b.get("covered") is True} == {0, 2}
        assert not any(b.get("covered") is False for b in blocks)
        assert view.ref.uncovered == _bits(set(range(n)) - {0, 2})
    finally:
        connection.rollback()
        connection.close()


def test_the_default_is_the_modal_value(parties: Path) -> None:
    """Ruling 7: when most blocks are covered, the default says so and the rest carry false."""
    connection = sqlite3.connect(_store(parties))
    try:
        segment, n = _biggest(connection)
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        _cover(connection, segment, _run_of(connection, 0, 20), [k for k in range(n) if k != 1])
        view = build_segment_view(connection, segment, billed=ENTITY_LLM)
        header, *blocks = _frames(view)
        assert header["defaults"]["covered"] is True
        assert [(b["ord"], b["covered"]) for b in blocks if "covered" in b] == [(1, False)]
        assert view.ref.uncovered == _bits({1})
    finally:
        connection.rollback()
        connection.close()


def _mentions(
    connection: sqlite3.Connection, view: ItemView, *, cost_class: str, at: list[int]
) -> tuple[int, int]:
    """A run over `view` mentioning one entity at each member ord in `at`; its written and
    quarantined-as-covered counts."""
    frames = {f["ord"]: f for f in _frames(view)[1:]}
    [(producer,)] = connection.execute("SELECT min(producer_id) FROM producer").fetchall()
    sink = SqliteGraphSink(connection)
    sink.begin_run(
        view.ref,
        PassIdentity(
            pass_id="derive.entity.llm",  # noqa: S106 -- a DriverId, not a credential.
            producer_id=int(producer),
            method=Method.LLM,
            origin_operator="op.derive",
            origin_driver="derive.entity.llm",
            driver_schema_v=1,
            cost_class=cost_class,
        ),
        frozenset(Cite(c) for c in view.cites),
    )
    tmp = TmpRef("t1")
    sink.entity(
        EntityDraft(
            key="probe", etype="org", title="Probe", scope="corpus",
            trust_claim=Trust.INFERRED, tmp=tmp,
        )
    )  # fmt: skip
    for k in at:
        text = frames[k]["text"]
        sink.mention(
            MentionDraft(
                entity=tmp, at=(Cite(frames[k]["cite"]), text[:12]), surface=text[:12],
                trust_claim=Trust.INFERRED,
            )
        )  # fmt: skip
    report = sink.end_run("ok", _NoSpend())
    written = connection.execute(
        "SELECT count(*) FROM mention WHERE run_id = ?", (report.run_id,)
    ).fetchone()[0]
    refused = connection.execute(
        "SELECT count(*) FROM quarantine WHERE run_id = ? AND code = ?",
        (report.run_id, OW_GRAPH_COVERED_GROUND),
    ).fetchone()[0]
    return int(written), int(refused)


class _NoSpend:
    calls = tokens_in = tokens_out = wall_ms = cpu_ms = gpu_ms = bytes_egress = 0
    provider = ""


def test_a_billed_run_is_refused_covered_ground(parties: Path) -> None:
    """06:788-797: an item on a block a cheaper Pass covered is OW_GRAPH_COVERED_GROUND."""
    connection = sqlite3.connect(_store(parties))
    try:
        segment, _ = _biggest(connection)
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        _cover(connection, segment, _run_of(connection, 0, 20), [0, 2])
        view = build_segment_view(connection, segment, billed=ENTITY_LLM)
        assert _mentions(connection, view, cost_class="billed_api", at=[0, 1, 2, 3]) == (2, 2)
    finally:
        connection.rollback()
        connection.close()


def test_a_free_run_has_no_floor(parties: Path) -> None:
    """The same cover, a free view: `uncovered` is None and nothing is refused (06:345)."""
    connection = sqlite3.connect(_store(parties))
    try:
        segment, _ = _biggest(connection)
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        _cover(connection, segment, _run_of(connection, 0, 20), [0, 2])
        view = build_segment_view(connection, segment)
        assert _mentions(connection, view, cost_class="free", at=[0, 1, 2, 3]) == (4, 0)
    finally:
        connection.rollback()
        connection.close()
