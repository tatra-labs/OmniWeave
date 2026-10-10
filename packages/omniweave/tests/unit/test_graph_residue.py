"""`ow graph residue` (D699): `ref_unresolved` plus `quarantine`, grouped."""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.store.graph_residue import graph_residue
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

CONTRACT = """# Loan Agreement

## 1. Definitions

"Business Day" means any day on which banks in London are open.

## 2. Payment

The Company pays on each Business Day, subject to Section 1, Section 9, clause 9 and ref GL-4471.

## 3. Notices

Notices follow ref GL-4471 and ISO-8601, Section 9 and Section 12.

## 4. Term

This lasts as Section 9 says, see Figure 9 and Table 9.
"""
RANKED = [
    ("section", "9", 4),
    ("identifier", "gl_4471", 2),
    ("figure", "9", 1),
    ("identifier", "iso_8601", 1),
    ("section", "12", 1),
    ("table", "9", 1),
]
"""Section 9 is worst and sorts after `figure`; the name `9` is unresolved under three kinds."""


@pytest.fixture(scope="module")
def contract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("residue")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "contract.md").write_text(CONTRACT, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return tmp_path


def _store(project: Path) -> Path:
    return project / ".omniweave" / "index.owstore"


def _count(connection: sqlite3.Connection, sql: str) -> int:
    [(n,)] = connection.execute(sql).fetchall()
    return int(n)


def test_the_unresolved_are_grouped_by_kind_and_name_worst_first(contract: Path) -> None:
    """Rulings 1 and 5: Section 9 four times (once spelled `clause 9`), then by kind and name."""
    connection = sqlite3.connect(_store(contract))
    try:
        found = graph_residue(connection)
        assert found.sites == _count(connection, "SELECT count(*) FROM ref_site")
        assert found.unresolved_sites == _count(connection, "SELECT count(*) FROM ref_unresolved")
        assert found.sites > found.unresolved_sites > 0, "Section 1 resolves; the rest do not"
        assert [(g.akind, g.name_norm, g.sites) for g in found.unresolved] == RANKED
        first = found.unresolved[0]
        assert (first.docs, first.surface) == (1, "Section 9"), "the least of two spellings"
        assert sum(g.sites for g in found.unresolved) == found.unresolved_sites
        assert not found.truncated
        assert (found.quarantined, found.quarantine) == (0, ())
    finally:
        connection.close()


def test_akind_narrows_the_references(contract: Path) -> None:
    """Ruling 4 on the reference half: identifiers only, and their own denominator."""
    connection = sqlite3.connect(_store(contract))
    try:
        found = graph_residue(connection, akind="identifier")
        assert {g.akind for g in found.unresolved} == {"identifier"}
        assert found.sites == _count(
            connection, "SELECT count(*) FROM ref_site WHERE akind = 'identifier'"
        )
        assert [(g.name_norm, g.sites) for g in found.unresolved] == [
            ("gl_4471", 2),
            ("iso_8601", 1),
        ]
        assert found.unresolved_sites == 3
        with pytest.raises(ValueError, match="identifier"):
            graph_residue(connection, akind="identifiers")
    finally:
        connection.close()


def test_the_ceiling_is_read_one_past(contract: Path) -> None:
    """Ruling 2: `truncated` is exact, and the site count is never cut."""
    connection = sqlite3.connect(_store(contract))
    try:
        every = graph_residue(connection)
        cut = graph_residue(connection, limit=1)
        assert (cut.unresolved, cut.truncated) == (every.unresolved[:1], True)
        assert cut.unresolved_sites == every.unresolved_sites
        whole = graph_residue(connection, limit=len(every.unresolved))
        assert (whole.unresolved, whole.truncated) == (every.unresolved, False)
    finally:
        connection.close()


def _quarantine(connection: sqlite3.Connection, row: tuple[str, str, str, int, int]) -> None:
    """`(code, row_kind, payload, at_gen, the run's offset among derive_run rows)`."""
    connection.execute(
        "INSERT INTO quarantine(code, run_id, row_kind, payload, at_gen)"
        " SELECT ?, run_id, ?, ?, ? FROM derive_run ORDER BY run_id LIMIT 1 OFFSET ?",
        row,
    )


def test_quarantine_is_grouped_by_code_and_kind(contract: Path) -> None:
    """Rulings 3 and 4: rows, runs and generations per group, and the draft's own kind."""
    connection = sqlite3.connect(_store(contract))
    try:
        _quarantine(connection, ("OW_GRAPH_UNGROUNDED", "entity", '{"title": "x"}', 2, 0))
        _quarantine(connection, ("OW_GRAPH_UNGROUNDED", "entity", '{"title": "y"}', 5, 1))
        _quarantine(connection, ("OW_GRAPH_UNGROUNDED", "entity", '{"title": "z"}', 3, 1))
        _quarantine(connection, ("OW_GRAPH_DANGLING_CITE", "xref", '{"akind": "identifier"}', 4, 0))
        _quarantine(connection, ("OW_GRAPH_UNPARSED_ITEM", "anchor", "not json", 4, 0))
        _quarantine(connection, ("OW_GRAPH_UNGROUNDED", "claim", '{"title": "w"}', 6, 0))
        found = graph_residue(connection)
        assert [
            (g.code, g.row_kind, g.rows, g.runs, g.first_gen, g.last_gen) for g in found.quarantine
        ] == [
            ("OW_GRAPH_UNGROUNDED", "entity", 3, 2, 2, 5),
            ("OW_GRAPH_DANGLING_CITE", "xref", 1, 1, 4, 4),
            ("OW_GRAPH_UNGROUNDED", "claim", 1, 1, 6, 6),
            ("OW_GRAPH_UNPARSED_ITEM", "anchor", 1, 1, 4, 4),
        ]
        assert found.quarantined == 6
        narrowed = graph_residue(connection, akind="identifier")
        assert [(g.code, g.rows) for g in narrowed.quarantine] == [("OW_GRAPH_DANGLING_CITE", 1)]
        assert graph_residue(connection, akind="section").quarantine == ()
    finally:
        connection.rollback()
        connection.close()


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_renders_both_halves(contract: Path) -> None:
    code, out, err = _verb(["residue", "--render", "json"], contract)
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    assert document["akind"] is None
    assert document["unresolved"][0]["surface"] == "Section 9"
    assert (document["quarantined"], document["quarantine"]) == (0, [])
    code, out, err = _verb(["residue", "--akind", "identifier"], contract)
    assert (code, err) == (0, ""), err
    lines = out.splitlines()
    assert lines[0].startswith("residue (identifier): 3 unresolved of ")
    assert any("GL-4471" in line for line in lines[1:])
    assert lines[-1] == "  nothing quarantined"


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["residue", "--akind", "identifiers"], 1),
        (["residue", "--quiet"], 1),
        (["residue", "--corpus", "other"], 2),
    ],
    ids=["unknown_kind", "quiet", "undeclared"],
)
def test_the_verbs_exits(contract: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, contract)
    assert got == code, err


def test_the_action_reads_and_has_no_tool() -> None:
    spec = ACTIONS["graph.residue"]
    assert (spec.mcp_name, spec.read_only, spec.destructive, spec.idempotent) == (
        None,
        True,
        False,
        True,
    )
