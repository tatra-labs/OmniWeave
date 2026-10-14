"""`ow graph types` (D706): the entity-type vocabulary, and an operator's promotions."""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.store.etypes import PROMOTED_PREFIX, promote, type_vocab
from test_graph_decide import _ingested, _store

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("types"))


def _propose(connection: sqlite3.Connection, *names: str) -> None:
    for name in names:
        connection.execute(
            "INSERT INTO etype_vocab(etype, scope, resolution, source) VALUES(?, 'corpus',"
            " 'fuzzy', 'proposed')",
            (name,),
        )


def test_the_vocabulary_by_source_then_name_with_live_entities(parties: Path) -> None:
    """Ruling 1: builtin, user, proposed; each with its live entities, counted."""
    connection = sqlite3.connect(_store(parties))
    try:
        _propose(connection, "covenant", "agency")
        connection.execute(
            "INSERT INTO etype_vocab(etype, scope, resolution, source) VALUES('zone', 'corpus',"
            " 'none', 'user')"
        )
        connection.execute("UPDATE entity SET state = 2 WHERE key = 'acme_holdings'")
        found = type_vocab(connection)
        sources = [e.source for e in found.etypes]
        assert sources == sorted(sources, key=["builtin", "user", "proposed"].index)
        builtin = [e.etype for e in found.etypes if e.source == "builtin"]
        assert builtin == sorted(builtin) and len(builtin) == 15
        assert [e.etype for e in found.etypes if e.source != "builtin"] == [
            "zone",
            "agency",
            "covenant",
        ]
        [(live,)] = connection.execute(
            "SELECT count(*) FROM entity WHERE etype = 'org' AND state = 0"
        ).fetchall()
        org = next(e for e in found.etypes if e.etype == "org")
        assert (org.entities, org.promoted) == (live, None)
        assert org.entities == 9, "ten parties, one retired"
    finally:
        connection.rollback()
        connection.close()


def test_a_promotion_makes_proposed_types_user_and_keeps_why(parties: Path) -> None:
    """Rulings 2 and 3: source becomes user, and meta keeps the reason and the generation."""
    connection = sqlite3.connect(_store(parties))
    try:
        _propose(connection, "covenant", "agency", "tranche")
        [(gen,)] = connection.execute("SELECT v FROM index_state WHERE k = 'generation'").fetchall()
        found = promote(
            connection, etypes=["covenant", " agency ", "covenant"], reason="the credit agreements"
        )
        assert found.promoted == ("covenant", "agency"), "named order, once each"
        by_name = {e.etype: e for e in found.etypes}
        assert (by_name["covenant"].source, by_name["agency"].source) == ("user", "user")
        assert by_name["tranche"].source == "proposed"
        assert by_name["covenant"].promoted is not None
        assert (by_name["covenant"].promoted.reason, by_name["covenant"].promoted.gen) == (
            "the credit agreements",
            int(gen),
        )
        [(record,)] = connection.execute(
            "SELECT v FROM meta WHERE k = ?", (PROMOTED_PREFIX + "agency",)
        ).fetchall()
        assert json.loads(record) == {"gen": int(gen), "reason": "the credit agreements"}
        assert type_vocab(connection).etypes == found.etypes, "read back the same"
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    "case",
    [
        (["covenant"], " ", UsageError, "needs a reason"),
        ([" ", ""], "x", UsageError, "names no type"),
        (["org"], "x", UsageError, "org is builtin"),
        (["covenant", "nope"], "x", NotFoundError, "no entity type 'nope'"),
        (["covenant", "org"], "x", UsageError, "already rendered"),
    ],
    ids=["blank_reason", "no_type", "builtin", "missing", "all_or_none"],
)
def test_the_refusals(parties: Path, case: tuple[list[str], str, type[Exception], str]) -> None:
    """Ruling 2: proposed only, and all of them or none."""
    etypes, reason, error, match = case
    connection = sqlite3.connect(_store(parties))
    try:
        _propose(connection, "covenant")
        with pytest.raises(error, match=match):
            promote(connection, etypes=etypes, reason=reason)
        [(source,)] = connection.execute(
            "SELECT source FROM etype_vocab WHERE etype = 'covenant'"
        ).fetchall()
        assert source == "proposed", "nothing was promoted"
        assert connection.execute(
            "SELECT count(*) FROM meta WHERE k LIKE 'graph.etype_%'"
        ).fetchone() == (0,)
    finally:
        connection.rollback()
        connection.close()


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_lists_then_promotes(tmp_path: Path) -> None:
    project = _ingested(tmp_path)
    connection = sqlite3.connect(_store(project))
    try:
        _propose(connection, "covenant", "agency")
        connection.commit()
    finally:
        connection.close()
    code, out, err = _verb(["types"], project)
    assert (code, err) == (0, ""), err
    lines = out.splitlines()
    assert lines[0] == "types: 15 builtin, 0 user, 2 proposed"
    assert "  org  corpus  fuzzy  builtin  10 entities" in lines
    assert lines[-1] == "  to keep them: ow graph types --promote agency,covenant --reason '<why>'"
    code, out, err = _verb(
        ["types", "--promote", "covenant", "--reason", "the loans", "--render", "json"], project
    )
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    assert document["promoted"] == ["covenant"]
    covenant = next(e for e in document["etypes"] if e["etype"] == "covenant")
    assert (covenant["source"], covenant["promoted"]["reason"]) == ("user", "the loans")
    code, out, _err = _verb(["types"], project)
    assert any(
        line.startswith("  covenant  corpus  fuzzy  user  0 entities  promoted at generation ")
        and line.endswith(": the loans")
        for line in out.splitlines()
    )
    code, _out, err = _verb(["types", "--promote", "covenant", "--reason", "again"], project)
    assert code == 1 and "covenant is user" in err


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["types", "--propose"], 1),
        (["types", "--promote", "x"], 1),
        (["types", "--promote", " , ", "--reason", "x"], 1),
        (["types", "--reason", "x"], 1),
        (["types", "--promote", "nope", "--reason", "x"], 2),
        (["types", "--quiet"], 1),
        (["types", "--corpus", "other"], 2),
    ],
    ids=["propose", "no_reason", "no_type", "reason_alone", "missing", "quiet", "undeclared"],
)
def test_the_verbs_exits(parties: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, parties)
    assert got == code, err


def test_the_action_writes_and_has_no_tool() -> None:
    spec = ACTIONS["graph.types"]
    assert (spec.mcp_name, spec.read_only, spec.destructive, spec.idempotent) == (
        None,
        False,
        False,
        True,
    )
