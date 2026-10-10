"""`graph.locate` (D694): an entity, a claim, an edge or a mention to one `Locus` per witness."""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.errors import NotFoundError
from omniweave_core.model.locus import LocusPrecision
from omniweave_core.store.locate import locate
from test_graph_cluster import PARTIES, _ids
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from collections.abc import Sequence


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The ten-party table, ingested: each party an entity with one mention and a `role` claim."""
    tmp_path = tmp_path_factory.mktemp("locate")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return tmp_path


def _store(project: Path) -> Path:
    return project / ".omniweave" / "index.owstore"


def _cite(connection: sqlite3.Connection, key: str) -> str:
    return f"e{_ids(connection)[key]}"


def test_an_entity_is_located_at_its_mention_with_the_reason_it_has_no_box(parties: Path) -> None:
    """A CSV's blocks have no geometry: the witness says where in the text, and why no box. The
    table's mention and the gazetteer's sit on one span (D683 keeps both as evidence)."""
    connection = sqlite3.connect(_store(parties))
    try:
        cite = _cite(connection, "acme_holdings")
        found = locate(connection, entity=cite)
        assert found.subject == cite
        assert len(found.witnesses) == 2
        assert len({w.locus for w in found.witnesses}) == 1, "one place, witnessed twice"
        witness = found.witnesses[0]
        assert (witness.kind, witness.slot, witness.entity) == ("mention", None, cite)
        assert witness.surface == "Acme Holdings"
        locus = witness.locus
        assert locus.quad is None and locus.reason is not None and "spatial" in locus.reason
        assert locus.precision is LocusPrecision.BLOCK
        assert locus.span.b - locus.span.a == len("Acme Holdings")
        assert str(locus.cite).startswith(f"d{locus.doc_ord}#")
        assert locate(connection, entity=cite.removeprefix("e")) == found, "the bare number too"
    finally:
        connection.close()


def test_a_merged_away_cite_locates_the_whole_closure(parties: Path) -> None:
    """Ruling 1: `e997` merged into `e412` locates both, each witness naming its member."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        connection.execute(
            "UPDATE entity SET canonical_id = ? WHERE entity_id = ?",
            (ids["acme_holdings"], ids["beta_corp"]),
        )
        found = locate(connection, entity=f"e{ids['beta_corp']}")
        assert found.subject == f"e{ids['acme_holdings']}", "the head an answer shows"
        assert [(w.entity, w.surface) for w in found.witnesses] == [
            (f"e{ids['acme_holdings']}", "Acme Holdings"),
            (f"e{ids['acme_holdings']}", "Acme Holdings"),
            (f"e{ids['beta_corp']}", "Beta Corp"),
            (f"e{ids['beta_corp']}", "Beta Corp"),
        ], "reading order: acme's row comes first"
    finally:
        connection.rollback()
        connection.close()


def test_a_claim_is_its_own_witness(parties: Path) -> None:
    """Ruling 4: the role cell the table's claim was observed in."""
    connection = sqlite3.connect(_store(parties))
    try:
        claim_id, cite = connection.execute(
            "SELECT c.claim_id, c.cite FROM claim c JOIN entity e ON e.entity_id ="
            " c.subject_entity WHERE e.key = 'acme_holdings'"
        ).fetchone()
        found = locate(connection, claim=str(cite))
        [witness] = found.witnesses
        assert (found.subject, witness.kind, witness.id) == (cite, "claim", claim_id)
        assert witness.surface == "Seller"
    finally:
        connection.close()


def _edge(connection: sqlite3.Connection, *, evidence: bool) -> int:
    ids = _ids(connection)
    connection.execute(
        "INSERT INTO edge(src_entity, dst_entity, relation, observed_block, ts_a, ts_b, run_id,"
        " trust) SELECT ?, ?, 'party_to', m.block_id, NULL, NULL, m.run_id, 1 FROM mention m"
        " WHERE m.entity_id = ?",
        (ids["acme_holdings"], ids["beta_corp"], ids["acme_holdings"]),
    )
    edge_id = int(connection.execute("SELECT MAX(edge_id) FROM edge").fetchone()[0])
    if evidence:
        for key, slot in (("beta_corp", "dst"), ("acme_holdings", "src")):
            connection.execute(
                "INSERT INTO edge_evidence(edge_id, mention_id, slot) SELECT ?, MIN(mention_id), ?"
                " FROM mention WHERE entity_id = ?",
                (edge_id, slot, ids[key]),
            )
    return edge_id


def test_an_edge_is_located_at_each_witness_in_its_slot(parties: Path) -> None:
    """06:203: `edge_evidence` is why there is one Locus per witness."""
    connection = sqlite3.connect(_store(parties))
    try:
        edge_id = _edge(connection, evidence=True)
        found = locate(connection, edge=edge_id)
        assert found.subject == f"edge {edge_id}"
        assert [(w.kind, w.slot, w.surface) for w in found.witnesses] == [
            ("mention", "src", "Acme Holdings"),
            ("mention", "dst", "Beta Corp"),
        ]
    finally:
        connection.rollback()
        connection.close()


def test_an_edge_with_no_evidence_is_located_at_its_own_observed_block(parties: Path) -> None:
    """Ruling 3: a blank answer would be the silence INV-9 forbids."""
    connection = sqlite3.connect(_store(parties))
    try:
        edge_id = _edge(connection, evidence=False)
        [witness] = locate(connection, edge=edge_id).witnesses
        assert (witness.kind, witness.id, witness.slot) == ("edge", edge_id, None)
        assert witness.surface == "Acme Holdings", "no span: the whole observed block"
    finally:
        connection.rollback()
        connection.close()


def test_a_witness_is_its_span_not_its_whole_block(parties: Path) -> None:
    """06:2068: the span is in the block's own text, and the Locus and the surface both carry it."""
    connection = sqlite3.connect(_store(parties))
    try:
        edge_id = _edge(connection, evidence=False)
        connection.execute("UPDATE edge SET ts_a = 0, ts_b = 4 WHERE edge_id = ?", (edge_id,))
        [witness] = locate(connection, edge=edge_id).witnesses
        assert (witness.surface, witness.locus.span.a, witness.locus.span.b) == ("Acme", 0, 4)
    finally:
        connection.rollback()
        connection.close()


def test_a_retired_mention_is_no_witness_of_its_entity(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        connection.execute(
            "UPDATE mention SET state = 1 WHERE entity_id = ?", (ids["kappa_foods"],)
        )
        assert locate(connection, entity=f"e{ids['kappa_foods']}").witnesses == ()
    finally:
        connection.rollback()
        connection.close()


def test_what_is_retired_is_no_witness_unless_asked_for_by_id(parties: Path) -> None:
    """Ruling 2."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        mention_id, block_id = connection.execute(
            "SELECT MIN(mention_id), block_id FROM mention WHERE entity_id = ?",
            (ids["iota_works"],),
        ).fetchone()
        connection.execute("UPDATE block SET state = 1 WHERE block_id = ?", (block_id,))
        assert locate(connection, entity=f"e{ids['iota_works']}").witnesses == ()
        [witness] = locate(connection, mention=mention_id).witnesses
        assert witness.surface == "Iota Works"
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    ("selector", "error"),
    [
        ({}, ValueError),
        ({"entity": "e1", "edge": 1}, ValueError),
        ({"entity": "k1"}, ValueError),
        ({"claim": "e1"}, ValueError),
        ({"entity": "e999999"}, NotFoundError),
        ({"claim": "k999999"}, NotFoundError),
        ({"edge": 999999}, NotFoundError),
        ({"mention": 999999}, NotFoundError),
    ],
    ids=["none", "two", "entity_sigil", "claim_sigil", "entity", "claim", "edge", "mention"],
)
def test_the_refusals(parties: Path, selector: dict[str, Any], error: type[Exception]) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        with pytest.raises(error):
            locate(connection, **selector)
    finally:
        connection.close()


# ---------------------------------------------------------------------------------------------
# `ow graph locate`
# ---------------------------------------------------------------------------------------------


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_render_json_is_the_located_and_each_locus(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        cite = _cite(connection, "acme_holdings")
    finally:
        connection.close()
    code, out, err = _verb(["locate", "--entity", cite, "--render", "json"], parties)
    assert (code, err) == (0, ""), err
    document = json.loads(out)
    assert (document["schema"], document["subject"]) == (1, cite)
    witness = document["witnesses"][0]
    assert witness["surface"] == "Acme Holdings"
    assert witness["quad"] is None and "spatial" in witness["reason"]
    assert witness["precision"] == "block"
    assert witness["origin"]["os_kind"]
    assert witness["span"][1] - witness["span"][0] == len("Acme Holdings")
    assert set(witness) >= {"cite", "doc_ord", "gen", "page", "addr", "entity", "slot", "kind"}


def test_render_text_is_one_line_per_witness(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        cite = _cite(connection, "acme_holdings")
    finally:
        connection.close()
    code, out, _err = _verb(["locate", "--entity", f"handbook:{cite}"], parties)
    assert code == 0
    head, *lines = out.rstrip("\n").split("\n")
    assert head == f"{cite}  2 witness(es)"
    assert all("'Acme Holdings'" in line and "no box:" in line for line in lines)


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["locate"], 1),
        (["locate", "--entity", "e1", "--mention", "1"], 1),
        (["locate", "--entity", "e999999"], 2),
        (["locate", "--entity", "e1", "--quiet"], 1),
        (["locate", "--entity", "e1", "--render", "rows"], 1),
        (["locate", "--entity", "other:e1"], 2),
        (["locate", "--entity", "other:e1", "--corpus", "handbook"], 6),
    ],
    ids=["none", "two", "missing", "quiet", "rows", "undeclared", "two_corpora"],
)
def test_the_verbs_exits(parties: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, parties)
    assert got == code, err


def test_the_action_is_read_only_free_and_listed_only_in_full() -> None:
    spec = ACTIONS["graph.locate"]
    assert (spec.mcp_name, spec.cli, spec.read_only, spec.destructive) == (
        "ow_locate",
        ("graph", "locate"),
        True,
        False,
    )
    assert spec.listed_in == frozenset({"full"})
