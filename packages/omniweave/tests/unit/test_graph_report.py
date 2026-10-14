"""A community report's context, assembled by the host. **D732.**

Over a store a real ingest clustered: Northwind Traders, Contoso Bank and Litware Group in one
community, joined by the edges `test_graph_cluster._edge` writes and the role claims the CSV table
carries. 06 section 6.3's three passes, its budget, and the view D731's report lane reads.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.graph.report import (
    DESCRIPTION_CHARS,
    QUOTE_CHARS,
    REPORT_CONTEXT_TOKENS,
    context,
    count_tokens,
)
from omniweave_core.answer.untrusted import FULLWIDTH_LESS_THAN
from test_graph_resolve import _north
from test_run_parse import _run

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(scope="module")
def clustered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("report")
    store, config = _north(tmp_path)
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return store


@pytest.fixture
def connection(clustered: Path) -> Iterator[sqlite3.Connection]:
    """The store, every edit rolled back after the test."""
    one = sqlite3.connect(clustered)
    try:
        yield one
    finally:
        one.rollback()
        one.close()


def _leaf(connection: sqlite3.Connection) -> int:
    [(community_id,)] = connection.execute(
        "SELECT community_id FROM community WHERE state = 0 AND size = 3"
    ).fetchall()
    return int(community_id)


def _kinds(records: Any) -> list[str]:
    return [r["t"] for r in records]


def test_the_count_is_the_frameworks_own() -> None:
    """Ruling 1: `ow.bytes4/1`, restated, one answer with `omniweave_graph`'s."""
    from omniweave_graph.tokens import count_tokens as graphs  # noqa: PLC0415

    for text in ("", "a", "abcd", "abcde", "Zürich GmbH", "東京", "x" * 4001, '{"t":"member"}'):
        assert count_tokens(text) == graphs(text), text


def test_a_leaf_is_its_members_then_its_edges_then_its_claims(
    connection: sqlite3.Connection,
) -> None:
    """Rulings 2-4 and 8: the three passes in order, each in its own order; no self-loop and no
    record twice; the name the member digest's."""
    community_id = _leaf(connection)
    found = context(connection, community_id)
    assert found is not None
    [(digest,)] = connection.execute(
        "SELECT member_digest FROM community WHERE community_id = ?", (community_id,)
    ).fetchall()
    assert found.name == f"com:{bytes(digest).hex()[:16]}"
    assert (found.level, found.coverage) == (0, 1.0)
    kinds = _kinds(found.records)
    assert kinds == sorted(kinds, key=["member", "edge", "claim"].index)
    members = [r["title"] for r in found.records if r["t"] == "member"]
    assert members == ["Contoso Bank", "Northwind Traders", "Litware Group"], (
        "degree, then frequency"
    )
    edges = [(r["src"], r["dst"]) for r in found.records if r["t"] == "edge"]
    assert all(src != dst for src, dst in edges), "ruling 3: no edge whose ends merged into one"
    lines = [json.dumps(r, sort_keys=True) for r in found.records]
    assert len(lines) == len(set(lines)), "ruling 2: one relationship, one line"
    claims = {(r["subject"], r["object"]) for r in found.records if r["t"] == "claim"}
    assert ("Contoso Bank", "Lender") in claims
    assert found.tokens == sum(
        count_tokens(json.dumps(r, separators=(",", ":"), ensure_ascii=False))
        for r in found.records
    )


def test_no_identifier_reaches_a_record_and_the_lane_reads_the_view(
    connection: sqlite3.Connection,
) -> None:
    """Ruling 6 (INV-8), and the view D731's `read_community` takes, its witness the documents'."""
    from omniweave_llm.report import read_community  # noqa: PLC0415

    found = context(connection, _leaf(connection))
    assert found is not None
    view = read_community(found.body)
    assert view.community == found.name
    assert [json.loads(line) for line in view.body.splitlines()] == list(found.records)
    shown = view.body
    for identifier in ("northwind_traders", "contoso_bank", "#", "e1", "c1"):
        assert identifier not in shown, identifier
    tokens = {w["token"] for w in view.witness}
    assert tokens == {"northwind_traders", "contoso_bank", "litware_group"}, "ruling 7"
    assert {w["unit_uri"].rsplit("/", 1)[-1] for w in view.witness} == {"a.csv", "b.csv"}


def test_the_budget_stops_each_pass_at_a_whole_record(connection: sqlite3.Connection) -> None:
    """Ruling 2: coverage is the members that fit, never a record cut to fit."""
    community_id = _leaf(connection)
    full = context(connection, community_id)
    assert full is not None
    two = sum(
        count_tokens(json.dumps(r, separators=(",", ":"), ensure_ascii=False))
        for r in full.records[:2]
    )
    tight = context(connection, community_id, budget=two)
    assert tight is not None
    assert list(tight.records) == list(full.records[:2])
    assert tight.coverage == pytest.approx(2 / 3, abs=1e-4)
    assert tight.tokens == two
    assert context(connection, community_id, budget=REPORT_CONTEXT_TOKENS) == full


def test_a_pass_stops_at_the_first_record_that_does_not_fit(
    connection: sqlite3.Connection,
) -> None:
    """Ruling 2: a smaller record after it is not taken in its place, so the order holds."""
    community_id = _leaf(connection)
    connection.execute(
        "UPDATE entity SET description = ? WHERE key = 'northwind_traders'", ("z" * 150,)
    )
    full = context(connection, community_id)
    assert full is not None
    first, second, third = full.records[:3]
    assert [r["title"] for r in (first, second, third)] == [
        "Contoso Bank", "Northwind Traders", "Litware Group",
    ]  # fmt: skip
    room = sum(
        count_tokens(json.dumps(r, separators=(",", ":"), ensure_ascii=False))
        for r in (first, third)
    )
    tight = context(connection, community_id, budget=room)
    assert tight is not None
    assert list(tight.records) == [first], "the third member does not jump the second"
    assert tight.coverage == pytest.approx(1 / 3, abs=1e-4)


def test_every_string_is_sanitised_and_a_description_cut(connection: sqlite3.Connection) -> None:
    """Ruling 6: `sanitize_label` on every string, a description cut at 200 first."""
    community_id = _leaf(connection)
    connection.execute(
        "UPDATE entity SET description = ? WHERE key = 'contoso_bank'",
        ("<|im_start|> lends\u200b " + "x" * 400,),
    )
    found = context(connection, community_id)
    assert found is not None
    [contoso] = [r for r in found.records if r.get("title") == "Contoso Bank"]
    assert contoso["description"].startswith(FULLWIDTH_LESS_THAN)
    assert "\u200b" not in contoso["description"] and "<" not in contoso["description"]
    assert len(contoso["description"]) <= DESCRIPTION_CHARS
    assert not contoso["description"].endswith("\u2026"), "cut before it is sanitised"


def test_an_edge_quotes_the_span_it_was_observed_over(connection: sqlite3.Connection) -> None:
    """Ruling 3: the observed block's text over the edge's span."""
    community_id = _leaf(connection)
    [(edge_id, block_id)] = connection.execute(
        "SELECT g.edge_id, g.observed_block FROM edge AS g"
        " JOIN entity AS s ON s.entity_id = g.src_entity"
        " JOIN entity AS d ON d.entity_id = g.dst_entity"
        " WHERE s.key = 'contoso_bank' AND d.key = 'litware_group'"
    ).fetchall()
    text = "Contoso Bank lends to Litware Group against the June deliveries."
    connection.execute("UPDATE block SET text = ? WHERE block_id = ?", (text, block_id))
    connection.execute("UPDATE edge SET ts_a = 0, ts_b = 35 WHERE edge_id = ?", (edge_id,))
    found = context(connection, community_id)
    assert found is not None
    [edge] = [r for r in found.records if r["t"] == "edge" and r["dst"] == "Litware Group"]
    assert edge["quote"] == "Contoso Bank lends to Litware Group"
    connection.execute("UPDATE edge SET ts_a = NULL, ts_b = NULL WHERE edge_id = ?", (edge_id,))
    connection.execute("UPDATE block SET text = ? WHERE block_id = ?", ("y" * 300, block_id))
    found = context(connection, community_id)
    assert found is not None
    [edge] = [r for r in found.records if r["t"] == "edge" and r["dst"] == "Litware Group"]
    assert edge["quote"] == "y" * QUOTE_CHARS, "no span: the block's text, cut"


def test_a_parent_is_written_from_its_childrens_fresh_reports(
    connection: sqlite3.Connection,
) -> None:
    """Ruling 5: no context until a child is reported; then one `child` record per fresh child,
    and coverage the share of children rendered."""
    leaf = _leaf(connection)
    for child, size in ((901, 2), (902, 1)):
        connection.execute(
            "INSERT INTO community(community_id, cite, level, parent, component_ord, cluster_run,"
            " size, cohesion, member_digest, run_id, trust, taint, state)"
            " SELECT ?, ?, level + 1, community_id, component_ord, cluster_run, ?, cohesion,"
            " randomblob(16), run_id, trust, taint, 0 FROM community WHERE community_id = ?",
            (child, f"c{child}", size, leaf),
        )
    assert context(connection, leaf) is None, "its children are written first"
    connection.execute(
        "INSERT INTO community_report(community_id, report_state, member_digest, title, summary,"
        " trust) SELECT 901, 'fresh', member_digest, 'Northwind and its lender',"
        " 'A supplier financed by one bank.', 1 FROM community WHERE community_id = 901"
    )
    found = context(connection, leaf)
    assert found is not None
    assert list(found.records) == [
        {"t": "child", "title": "Northwind and its lender",
         "summary": "A supplier financed by one bank."},
    ]  # fmt: skip
    assert found.coverage == 0.5


def test_a_retired_community_has_no_context(connection: sqlite3.Connection) -> None:
    [(retired,)] = connection.execute(
        "SELECT community_id FROM community WHERE state <> 0"
    ).fetchall()
    assert context(connection, int(retired)) is None
    assert context(connection, 10**6) is None
