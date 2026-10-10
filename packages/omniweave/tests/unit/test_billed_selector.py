"""The billed selector (06:744-773) and the billed roster's gates. **D714.**

`eligible()` is the query that hands a billed Pass its Segments, one document at a time. The roster
is which billed Passes a run may schedule at all: both activation lists must name one, and
`resolve()` must admit it.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.run import ingest as ingest_module
from omniweave.run.operators.derive import FREE_PASSES, DerivePlan
from omniweave.run.routing import resolve_policy
from omniweave_core.config import SHIPPED_DRIVERS, SHIPPED_PASSES, load
from omniweave_core.discovery import catalog
from omniweave_core.limits import MAX_SEGMENT_BLOCKS
from omniweave_core.model.enums import Kind, Layer
from omniweave_core.store.coverage import (
    FORM_KINDS,
    LANE_KINDS,
    PROSE_KINDS,
    TEXT_KINDS,
    eligible,
    kind_bits,
)
from test_graph_plan import _cover, _ingested, _run_of
from test_graph_residue import _store
from test_run_derive import _ctx
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from pathlib import Path

ENTITY_LLM = (2, 10)
LLM = "derive.entity.llm"


@pytest.fixture(scope="module")
def contract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("selector"))


def _live(connection: sqlite3.Connection) -> list[tuple[int, int, int, bytes]]:
    """Every live Segment at its head generation: id, n_blocks, doc_ord, content_digest."""
    return [
        (int(s), int(n), int(d), bytes(c))
        for s, n, d, c in connection.execute(
            "SELECT s.segment_id, s.n_blocks, s.doc_ord, s.content_digest FROM segment AS s"
            " JOIN doc AS d ON d.doc_ord = s.doc_ord AND d.gen = s.gen"
            " WHERE s.state = 0 AND s.layer = 0 ORDER BY s.segment_id"
        )
    ]


def _member(n: int) -> int:
    return ((1 << n) - 1) << (MAX_SEGMENT_BLOCKS - n)


def _found(connection: sqlite3.Connection, doc: int, **kwargs: Any) -> dict[int, Any]:
    arguments: dict[str, Any] = {"lane": "entity", "before": ENTITY_LLM, "floor": 0.6}
    arguments.update(kwargs)
    return {e.segment_id: e for e in eligible(connection, doc_ord=doc, **arguments)}


def test_an_uncovered_document_hands_over_every_body_segment_whole(contract: Path) -> None:
    """Ruling 9: the part is `seg:` and sixteen hex of the digest, and nothing is covered."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        live = _live(connection)
        doc = live[0][2]
        found = _found(connection, doc)
        mine = [row for row in live if row[2] == doc]
        assert sorted(found) == [s for s, *_ in mine]
        for segment, n, _doc, digest in mine:
            assert found[segment].part == f"seg:{digest.hex()[:16]}"
            assert found[segment].uncovered == _member(n).to_bytes(64, "big")
    finally:
        connection.rollback()
        connection.close()


def test_cheaper_cover_under_the_floor_is_left_out_of_what_is_handed_over(
    contract: Path,
) -> None:
    """06:766-773: only cheaper cover counts, and at or over the floor a Segment stays out."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        live = sorted(_live(connection), key=lambda row: -row[1])
        (s1, n1, doc, _d1), (s2, n2, *_rest) = (
            live[0],
            next(r for r in live[1:] if r[2] == live[0][2]),
        )
        assert n1 >= 2
        free, later = _run_of(connection, 0, 20), _run_of(connection, 2, 50)
        _cover(connection, s1, free, [0])
        _cover(connection, s1, later, range(n1))
        _cover(connection, s2, free, range(n2))
        found = _found(connection, doc)
        assert s2 not in found, "wholly covered by a cheaper Pass"
        assert found[s1].uncovered == (_member(n1) & ~_member(1)).to_bytes(64, "big")
        assert s1 not in _found(connection, doc, floor=1 / n1), "the floor is strict"
        assert s1 in _found(connection, doc, floor=1 / n1 + 1e-9)
    finally:
        connection.rollback()
        connection.close()


def test_retired_furniture_restricted_and_other_documents_are_never_handed_over(
    contract: Path,
) -> None:
    """Rulings 6-8: the layer, the lane's Kinds, the denied bits, the document, the live state."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        live = _live(connection)
        doc = live[0][2]
        mine = [s for s, _n, d, _c in live if d == doc]
        assert len(mine) >= 4, "the contract has four sections"
        retired, furniture, pictured, restricted = mine[:4]
        connection.execute("UPDATE segment SET state = 1 WHERE segment_id = ?", (retired,))
        connection.execute("UPDATE segment SET layer = 1 WHERE segment_id = ?", (furniture,))
        connection.execute(
            "UPDATE segment SET kind_mask = ? WHERE segment_id = ?",
            (kind_bits([Kind.PICTURE, Kind.RULE]), pictured),
        )
        connection.execute(
            "UPDATE segment SET restriction_bits = 4 WHERE segment_id = ?", (restricted,)
        )
        found = _found(connection, doc)
        assert set(found).isdisjoint({retired, furniture, pictured})
        assert restricted in found, "no bit is denied by default"
        assert restricted not in _found(connection, doc, deny_bits=4)
        assert furniture in _found(connection, doc, layers=frozenset({Layer.FURNITURE}))
        assert _found(connection, doc + 1_000) == {}
    finally:
        connection.rollback()
        connection.close()


def test_a_lanes_kinds_are_the_segmenters_bits_and_03s_text_column(contract: Path) -> None:
    """Ruling 6: `1 << enum_val.ord`, as the segmenter sets `kind_mask`."""
    connection = sqlite3.connect(_store(contract))
    try:
        ords = dict(connection.execute("SELECT name, ord FROM enum_val WHERE domain = 'kind'"))
    finally:
        connection.close()
    assert kind_bits([Kind.PARAGRAPH, Kind.TABLE_CELL]) == (
        (1 << ords["paragraph"]) | (1 << ords["table_cell"])
    )
    assert LANE_KINDS["anchor"] == LANE_KINDS["entity"] == kind_bits(TEXT_KINDS)
    assert LANE_KINDS["xref"] == kind_bits(PROSE_KINDS | {Kind.TABLE_CELL})
    assert LANE_KINDS["claim"] == LANE_KINDS["xref"] | kind_bits(FORM_KINDS)
    assert {k.value for k in Kind} - {k.value for k in TEXT_KINDS} == {
        "document", "section", "list", "blockquote", "table", "figure", "picture", "rule",
        "form", "checkbox", "key_value", "toc", "bibliography", "diagram", "container",
    }, "03 section 4.1: text is NULL on exactly these"  # fmt: skip
    assert {k.value for k in TEXT_KINDS - PROSE_KINDS} == {
        "code", "table_cell", "formula", "page_header", "page_footer", "form_field",
        "toc_entry", "reference", "chemical", "unknown",
    }, "prose is running text: no code, math, entry, field, furniture or cell"  # fmt: skip


OPEN = "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"


def _policy(tmp_path: Path, *, enabled: bool, billed: bool, offline: bool = False) -> Any:
    drivers = [*SHIPPED_DRIVERS, *([LLM] if enabled else [])]
    classes = ["free", "local_compute", *(["billed_api"] if billed else [])]
    (tmp_path / "omniweave.toml").write_text(
        OPEN
        + f"enabled = {drivers!r}\n[drivers.cost]\nallow_classes = {classes!r}\n".replace("'", '"'),
        encoding="utf-8",
    )
    return resolve_policy(load(cwd=tmp_path, env={}), offline=offline)


def test_a_billed_pass_no_list_names_is_not_planned_and_not_reported(tmp_path: Path) -> None:
    derives, why = DerivePlan.of(catalog(), _policy(tmp_path, enabled=True, billed=True), _ctx())
    assert derives is not None
    assert (derives.billed, why) == ((), "")
    assert [c.card.identity.id for c in derives.passes] == list(FREE_PASSES)


def test_both_lists_and_resolve_gate_a_billed_pass(tmp_path: Path) -> None:
    """08:1977-1979: `[graph.passes] enable` and `[drivers] enabled` both apply; resolve() last."""
    enable = (*SHIPPED_PASSES, LLM)
    derives, why = DerivePlan.of(
        catalog(), _policy(tmp_path, enabled=False, billed=True), _ctx(), enable=enable
    )
    assert derives is not None and derives.billed == ()
    assert why == f"{LLM}: [graph.passes] enable names it, [drivers] enabled does not"
    derives, why = DerivePlan.of(
        catalog(), _policy(tmp_path, enabled=True, billed=False), _ctx(), enable=enable
    )
    assert derives is not None and derives.billed == ()
    assert why.startswith(f"{LLM}: cost_class_not_permitted: "), why
    assert "allow_classes" in why
    derives, why = DerivePlan.of(
        catalog(), _policy(tmp_path, enabled=True, billed=True), _ctx(), enable=enable
    )
    assert derives is not None and why == ""
    assert [c.card.identity.id for c in derives.billed] == [LLM]
    assert [c.card.identity.id for c in derives.passes] == list(FREE_PASSES)


def test_an_offline_run_refuses_a_billed_pass_that_needs_the_network(tmp_path: Path) -> None:
    derives, why = DerivePlan.of(
        catalog(),
        _policy(tmp_path, enabled=True, billed=True, offline=True),
        _ctx(),
        enable=(LLM,),
    )
    assert derives is not None and derives.billed == ()
    assert why.startswith(f"{LLM}: hardware_absent: "), why
    assert "network" in why, why


def test_the_run_reads_graph_passes_enable(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(
        f'[graph.passes]\nenable = ["{LLM}"]\n', encoding="utf-8"
    )
    inputs = ingest_module._routing_inputs(load(cwd=tmp_path, env={}))
    assert inputs.passes == frozenset({LLM})


def test_a_billed_pass_alone_is_still_a_plan(tmp_path: Path) -> None:
    """Lock only the billed Pass: every free Pass is refused and the plan is the billed one."""
    policy = replace(
        _policy(tmp_path, enabled=True, billed=True), require_lock=True, locked_ids=frozenset({LLM})
    )
    derives, why = DerivePlan.of(catalog(), policy, _ctx(), enable=(LLM,))
    assert derives is not None, why
    assert (derives.passes, [c.card.identity.id for c in derives.billed]) == ((), [LLM])


def test_an_ingest_names_the_gate_that_kept_a_billed_pass_out(tmp_path: Path) -> None:
    """`[graph.passes] enable` reaches the run's plan, and the report says which list is short."""
    store, _ = _project(tmp_path, ())
    with (tmp_path / "omniweave.toml").open("a", encoding="utf-8") as toml:
        toml.write(f"[graph.passes]\nenable = {[*SHIPPED_PASSES, LLM]!r}\n".replace("'", '"'))
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    (tmp_path / "docs" / "memo.md").write_text("# Memo\n\nSee clause 4.\n", encoding="utf-8")
    lines = _run(tmp_path, store, config).lines()
    expected = f"{LLM}: [graph.passes] enable names it, [drivers] enabled does not"
    assert any(line.startswith("  derive    not enqueued: ") and expected in line for line in lines)


def test_a_binding_lane_hands_over_only_segments_its_bound_lane_covered(contract: Path) -> None:
    """D724, 06:841: the claim lane runs only where `entity` cover exists to bind subjects."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover")
        live = _live(connection)
        doc = live[0][2]
        bound, empty, bare = [s for s, _n, d, _c in live if d == doc][:3]
        run = _run_of(connection, 2, 10)
        _cover(connection, bound, run, [0])
        _cover(connection, empty, run, [])
        found = _found(connection, doc, lane="claim", before=(2, 20), bound="entity")
        assert bound in found
        assert empty not in found, "a Pass that looked and found nothing binds nothing"
        assert bare not in found
        unbound = _found(connection, doc, lane="claim", before=(2, 20))
        assert {bound, empty, bare} <= set(unbound)
    finally:
        connection.rollback()
        connection.close()
