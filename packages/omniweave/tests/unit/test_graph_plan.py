"""`ow graph plan` (D705): per billed lane, coverage and the projected Spend, before a run."""

from __future__ import annotations

import io
import json
import secrets
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.store.coverage import BILLED_PASSES, graph_plan, lane_coverage
from test_graph_residue import CONTRACT, _store
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

ENTITY_LLM = (2, 10)


def _ingested(tmp_path: Path) -> Path:
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "contract.md").write_text(CONTRACT, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return tmp_path


@pytest.fixture(scope="module")
def contract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("plan"))


def _copy(connection: sqlite3.Connection, table: str, key: str, overrides: dict[str, str]) -> int:
    """A copy of `table`'s first row with `overrides` (SQL expressions); SQLite assigns `key`."""
    columns = [str(r[1]) for r in connection.execute(f"PRAGMA table_info({table})") if r[1] != key]
    picked = ", ".join(overrides.get(c, c) for c in columns)
    cursor = connection.execute(
        f"INSERT INTO {table}({', '.join(columns)}) SELECT {picked} FROM {table} LIMIT 1"  # noqa: S608
    )
    return int(cursor.lastrowid or 0)


def _run_of(connection: sqlite3.Connection, rank: int | None, phase: int = 50) -> int:
    """A derive_run of a fresh Pass at `(rank, phase)`, or of an unregistered Pass for `None`."""
    pass_id = f"derive.test.{secrets.token_hex(4)}"
    if rank is not None:
        _copy(
            connection,
            "derive_pass",
            "",
            {"pass_id": f"'{pass_id}'", "cost_rank": str(rank), "phase": str(phase)},
        )
    return _copy(
        connection,
        "derive_run",
        "run_id",
        {
            "pass_id": f"'{pass_id}'",
            "cache_key": f"'{secrets.token_hex(32)}'",
            "at_gen": str(1_000_000 + secrets.randbelow(1_000_000)),
        },
    )


def _cover(connection: sqlite3.Connection, segment: int, run: int, ords: Iterable[int]) -> None:
    """One cover row on the entity lane, written high bit first as the sink writes it (D703)."""
    covered = list(ords)
    bits = bytearray(64)
    for k in covered:
        bits[k // 8] |= 0x80 >> (k % 8)
    connection.execute(
        "INSERT INTO derive_cover(segment_id, lane, run_id, cover_bits, n_covered)"
        " VALUES(?, 'entity', ?, ?, ?)",
        (segment, run, bytes(bits), len(covered)),
    )


def _segments(connection: sqlite3.Connection) -> list[tuple[int, int]]:
    return [
        (int(s), int(n))
        for s, n in connection.execute(
            "SELECT s.segment_id, s.n_blocks FROM segment AS s"
            " JOIN doc AS d ON d.doc_ord = s.doc_ord AND d.gen = s.gen WHERE s.state = 0"
            " ORDER BY s.segment_id"
        )
    ]


def test_an_uncovered_lane_is_billed_whole(contract: Path) -> None:
    """Rulings 1, 2 and 4: no cover on the lane, every live Segment billed, one row each."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        connection.execute(
            "UPDATE segment SET state = 1 WHERE segment_id = (SELECT max(segment_id) FROM segment)"
        )
        segments = _segments(connection)
        assert len(segments) >= 3, "the contract has four sections, one now retired"
        found = lane_coverage(connection, lane="entity", before=ENTITY_LLM, floor=0.6)
        assert (found.segments, found.rows, found.billed) == (len(segments),) * 3
        assert (found.mean_covered, found.mean_uncovered_billed, found.billed_share) == (0, 1, 1)
    finally:
        connection.rollback()
        connection.close()


def test_cover_counts_only_from_cheaper_passes_and_inside_the_segment(contract: Path) -> None:
    """Rulings 1 and 3: what is OR-ed, what is masked, and what is not cheaper."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        segments = _segments(connection)
        (s1, n1), (s2, n2), (s3, n3), (s4, n4) = sorted(segments, key=lambda sn: -sn[1])[:4]
        assert n1 >= 2, "two halves, neither enough alone"
        free, also_free = _run_of(connection, 0, 20), _run_of(connection, 0, 30)
        earlier_billed, later_billed = _run_of(connection, 2, 5), _run_of(connection, 2, 20)
        unplaced = _run_of(connection, None)
        _cover(connection, s1, free, range(n1 // 2))
        _cover(connection, s1, also_free, range(n1 // 2, n1))
        _cover(connection, s2, later_billed, range(n2))
        _cover(connection, s2, unplaced, range(n2))
        _cover(connection, s3, free, [n3])
        _cover(connection, s4, earlier_billed, range(n4))
        found = lane_coverage(connection, lane="entity", before=ENTITY_LLM, floor=0.6)
        covered = {s1: 1.0, s4: 1.0}
        expect = [covered.get(s, 0.0) for s, _ in segments]
        assert found.mean_covered == pytest.approx(sum(expect) / len(expect))
        assert found.billed == len(segments) - 2, "s2's cover is later or unplaced; s3's is outside"
        assert found.billed_share == pytest.approx((len(segments) - 2) / len(segments))
        assert found.rows == len(segments) + 2, "s1 and s2 stream two cover rows each"
        later = lane_coverage(connection, lane="entity", before=(2, 30), floor=0.6)
        assert later.billed == len(segments) - 3, "at (2, 30) the (2, 20) cover is cheaper"
    finally:
        connection.rollback()
        connection.close()


def test_the_floor_is_strict(contract: Path) -> None:
    """06:2629: a Segment is billed when its covered_frac falls BELOW the floor."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover WHERE lane = 'entity'")
        segments = _segments(connection)
        s, n = max(segments, key=lambda sn: sn[1])
        assert n >= 2
        _cover(connection, s, _run_of(connection, 0), range(n // 2))
        frac = (n // 2) / n
        at = lane_coverage(connection, lane="entity", before=ENTITY_LLM, floor=frac)
        above = lane_coverage(connection, lane="entity", before=ENTITY_LLM, floor=frac + 1e-9)
        assert above.billed == at.billed + 1
        assert above.mean_uncovered_billed is not None
    finally:
        connection.rollback()
        connection.close()


def test_the_plan_projects_spend_per_billed_segment(contract: Path) -> None:
    """Ruling 5: 06:837-838's projections times the billed Segments, calls rounded half up."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover")
        segments = len(_segments(connection))
        plan = graph_plan(connection, floor=0.6)
        assert [lane.pass_id for lane in plan.lanes] == [b.pass_id for b in BILLED_PASSES]
        entity, claim = plan.lanes
        assert (entity.coverage.lane, claim.coverage.lane) == ("entity", "claim")
        assert (entity.tokens_in, entity.tokens_out) == (3989 * segments, 806 * segments)
        assert entity.calls == int(1.35 * segments + 0.5 + 1e-9)
        assert (claim.calls, claim.tokens_in, claim.tokens_out) == (
            segments,
            3100 * segments,
            480 * segments,
        )
    finally:
        connection.rollback()
        connection.close()


def test_a_registered_billed_pass_is_placed_by_its_row(contract: Path) -> None:
    """Ruling 5: a derive_pass row for derive.entity.llm moves it, and with it what is cheaper."""
    connection = sqlite3.connect(_store(contract))
    try:
        connection.execute("DELETE FROM derive_cover")
        s, n = _segments(connection)[0]
        _cover(connection, s, _run_of(connection, 1, 0), range(n))
        before = graph_plan(connection, floor=0.6).lanes[0].coverage.billed
        _copy(
            connection,
            "derive_pass",
            "",
            {"pass_id": "'derive.entity.llm'", "cost_rank": "1", "phase": "0"},
        )
        after = graph_plan(connection, floor=0.6).lanes[0].coverage.billed
        assert after == before + 1, "at (1, 0) the (1, 0) cover is no longer cheaper"
    finally:
        connection.rollback()
        connection.close()


def test_calls_round_half_up() -> None:
    from decimal import ROUND_HALF_UP, Decimal  # noqa: PLC0415

    assert int((Decimal("1.35") * 10).quantize(Decimal(1), rounding=ROUND_HALF_UP)) == 14


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_renders_the_plan(contract: Path) -> None:
    code, out, err = _verb(["plan", "--render", "json"], contract)
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    assert document["floor"] == 0.6
    assert [lane["pass_id"] for lane in document["lanes"]] == [b.pass_id for b in BILLED_PASSES]
    entity = document["lanes"][0]
    assert set(entity["coverage"]) >= {"segments", "rows", "mean_covered", "billed", "billed_share"}
    code, out, err = _verb(["plan"], contract)
    assert (code, err) == (0, ""), err
    lines = out.splitlines()
    assert lines[0] == "plan: llm_coverage_floor 0.60; a projection, never a price (06:821)"
    assert lines[1].startswith("  entity  derive.entity.llm  ")


@pytest.mark.parametrize(
    ("argv", "code"),
    [(["plan", "--quiet"], 1), (["plan", "--corpus", "other"], 2)],
    ids=["quiet", "undeclared"],
)
def test_the_verbs_exits(contract: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, contract)
    assert got == code, err


def test_the_action_reads_and_has_no_tool() -> None:
    spec = ACTIONS["graph.plan"]
    assert (spec.mcp_name, spec.read_only, spec.destructive, spec.idempotent) == (
        None,
        True,
        False,
        True,
    )
