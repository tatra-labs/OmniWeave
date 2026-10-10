"""`ow graph why --cite` (D695): every entity, edge and claim observed in one block."""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.store.observed import observed
from test_graph_cluster import PARTIES, _ids
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from collections.abc import Sequence


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("why")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return tmp_path


def _store(project: Path) -> Path:
    return project / ".omniweave" / "index.owstore"


def _cells(connection: sqlite3.Connection) -> tuple[int, int]:
    """acme's subject cell and the role cell its claim was observed in."""
    subject = connection.execute(
        "SELECT MIN(m.block_id) FROM mention m JOIN entity e USING (entity_id)"
        " WHERE e.key = 'acme_holdings'"
    ).fetchone()[0]
    role = connection.execute(
        "SELECT c.observed_block FROM claim c JOIN entity e ON e.entity_id = c.subject_entity"
        " WHERE e.key = 'acme_holdings'"
    ).fetchone()[0]
    return int(subject), int(role)


def test_a_subject_cell_asserts_its_entity_and_a_role_cell_its_claim(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        subject, role = _cells(connection)
        ids = _ids(connection)
        named = observed(connection, subject)
        assert named is not None
        assert {(m.entity, m.key, m.surface) for m in named.mentions} == {
            (f"e{ids['acme_holdings']}", "acme_holdings", "Acme Holdings")
        }
        assert len(named.mentions) == 2, "the table's and the gazetteer's, on one span"
        assert (named.edges, named.claims) == ((), ())
        claimed = observed(connection, role)
        assert claimed is not None and claimed.mentions == ()
        [claim] = claimed.claims
        assert (claim.subject, claim.predicate, claim.object, claim.status) == (
            f"e{ids['acme_holdings']}",
            "role",
            "Seller",
            "asserted",
        )
        assert claim.span == (0, len("Seller"))
        assert observed(connection, 10**12) is None
    finally:
        connection.close()


def test_mentions_name_their_head_and_retired_ones_are_not_assertions(parties: Path) -> None:
    """Rulings 1 and 2."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        subject, _role = _cells(connection)
        connection.execute(
            "UPDATE entity SET canonical_id = ? WHERE entity_id = ?",
            (ids["beta_corp"], ids["acme_holdings"]),
        )
        found = observed(connection, subject)
        assert found is not None
        assert {m.head for m in found.mentions} == {f"e{ids['beta_corp']}"}
        connection.execute("UPDATE mention SET state = 1 WHERE block_id = ?", (subject,))
        found = observed(connection, subject)
        assert found is not None and found.mentions == ()
    finally:
        connection.rollback()
        connection.close()


def test_an_edge_observed_here_is_listed_with_its_span_or_none(parties: Path) -> None:
    """Rulings 2-4: every edge observed in the block, in span order, `None` when it had none."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        subject, _role = _cells(connection)
        for relation, ts_a, ts_b in (("party_to", 5, 13), ("related_to", None, None)):
            connection.execute(
                "INSERT INTO edge(src_entity, dst_entity, relation, observed_block, ts_a, ts_b,"
                " run_id, trust) SELECT ?, ?, ?, ?, ?, ?, MIN(run_id), 1 FROM derive_run",
                (ids["acme_holdings"], ids["beta_corp"], relation, subject, ts_a, ts_b),
            )
        found = observed(connection, subject)
        assert found is not None
        assert [(e.relation, e.span) for e in found.edges] == [
            ("related_to", None),
            ("party_to", (5, 13)),
        ], "no span sorts first: the whole block"
        assert {(e.src, e.dst) for e in found.edges} == {
            (f"e{ids['acme_holdings']}", f"e{ids['beta_corp']}")
        }
    finally:
        connection.rollback()
        connection.close()


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _cite(parties: Path, block_id: int) -> str:
    connection = sqlite3.connect(_store(parties))
    try:
        return str(
            connection.execute("SELECT cite FROM block WHERE block_id = ?", (block_id,)).fetchone()[
                0
            ]
        )
    finally:
        connection.close()


def test_render_json_is_the_observed(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        _subject, role = _cells(connection)
    finally:
        connection.close()
    cite = _cite(parties, role)
    code, out, err = _verb(["why", "--cite", cite, "--render", "json"], parties)
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    assert (document["schema"], document["cite"], document["mentions"]) == (1, cite, [])
    [claim] = document["claims"]
    assert (claim["predicate"], claim["object"], claim["span"]) == ("role", "Seller", [0, 6])


def test_render_text_is_a_head_and_a_line_per_row(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        subject, _role = _cells(connection)
    finally:
        connection.close()
    cite = _cite(parties, subject)
    code, out, _err = _verb(["why", "--cite", cite], parties)
    assert code == 0
    head, *lines = out.rstrip("\n").split("\n")
    assert head == f"{cite}  2 mention(s), 0 edge(s), 0 claim(s)"
    assert all("(org acme_holdings)" in line and "'Acme Holdings'" in line for line in lines)


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["why"], 1),
        (["why", "--cite", " "], 1),
        (["why", "--cite", "d1#999999"], 2),
        (["why", "--cite", "d1#1", "--quiet"], 1),
        (["why", "--cite", "d1#1", "--render", "jsonl"], 1),
    ],
    ids=["no_cite", "blank", "missing", "quiet", "jsonl"],
)
def test_the_verbs_exits(parties: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, parties)
    assert got == code, err


@pytest.mark.parametrize("argv", [["why"], ["why", "--cite", " "]], ids=["none", "blank"])
def test_a_missing_or_blank_cite_names_the_flag(parties: Path, argv: list[str]) -> None:
    got, _out, err = _verb(argv, parties)
    assert got == 1
    assert "needs --cite" in err, err


def test_a_mention_is_its_span_and_a_claims_object_may_be_an_entity(parties: Path) -> None:
    """06:2121: each row with its span; a claim's object is an entity's cite when it has one."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        subject, _role = _cells(connection)
        connection.execute(
            "INSERT INTO mention(entity_id, block_id, segment_id, ts_a, ts_b, surface, run_id,"
            " trust, digest) SELECT entity_id, block_id, segment_id, 0, 4, 'Acme', run_id, trust,"
            " X'00' FROM mention WHERE block_id = ? LIMIT 1",
            (subject,),
        )
        connection.execute(
            "INSERT INTO claim(cite, subject_entity, object_entity, claim_type, predicate,"
            " description, status, observed_block, ts_a, ts_b, quote_tier, run_id, trust)"
            " SELECT 'k99999', ?, ?, 'relation', 'partner', '', 'asserted', ?, 0, 4, 0,"
            " MIN(run_id), 1 FROM derive_run",
            (ids["acme_holdings"], ids["beta_corp"], subject),
        )
        found = observed(connection, subject)
        assert found is not None
        first = found.mentions[0]
        assert (first.span, first.surface) == ((0, 4), "Acme"), "span order: the shorter first"
        [claim] = found.claims
        assert (claim.claim, claim.object) == ("k99999", f"e{ids['beta_corp']}")
    finally:
        connection.rollback()
        connection.close()


def test_the_action_has_no_tool_and_is_read_only() -> None:
    """10:807's roster names no tool for it (`ow_why` is `route.explain`)."""
    spec = ACTIONS["graph.why"]
    assert (spec.mcp_name, spec.listed_in, spec.cli, spec.read_only) == (
        None,
        frozenset(),
        ("graph", "why"),
        True,
    )
