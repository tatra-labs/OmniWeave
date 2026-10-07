"""D668 and D669 end to end: `ow add` runs the free Passes over what it segments, in one drain.

A contract in Markdown through a real `ow add`: it is parsed, segmented, and the segmentation's
transaction enqueues one row per free Pass -- `derive.anchor` and `derive.xref`; the drain claims
them, real workers run the discovered `derive.anchor.defterm` and `derive.xref.pattern` over the
document's Segments in one unit each, and the store holds a `derive_pass` row per card, one
`derive_run` per Segment per Pass with its cover, the defined terms as anchors, entities and
aliases, and the references as `ref_site` occurrences that `ref_unresolved` reports -- nothing
defines a section or a schedule yet. A second `ow add` over the same file derives nothing.
"""

from __future__ import annotations

import os
import sqlite3  # noqa: TID251 -- the assertions read the store the run wrote.
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
CONTRACT = """# Loan Agreement

International Business Machines Corporation ("IBM") and Acme Holdings Ltd.
(hereinafter, the "Company") agree as follows.

## 1. Definitions

"Business Day" means any day on which banks in London are open.

"Lender" shall have the meaning set forth in Schedule 1.

## 2. Payment

The Company pays IBM on each Business Day, subject to Section 1 and ref GL-4471.
"""
DEFTERM = "derive.anchor.defterm"
XREF = "derive.xref.pattern"
TIMEOUT_S = 300


def _run(project: Path, env: dict[str, str], *argv: str) -> tuple[int | None, str]:
    done = run_captured(
        (sys.executable, "-m", "omniweave", *argv),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=TIMEOUT_S,
    )
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")


def _rows(store: Path, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(store)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_an_add_runs_every_free_pass_over_every_document_it_segments(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    (project / "docs" / "loan.md").write_text(CONTRACT, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    env = {
        **keep,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(tmp_path / "ow"),
    }
    code, shown = _run(project, env, "add", "docs")
    assert code == 0, shown[-3000:]
    assert "  segment   1 document(s): " in shown, shown[-3000:]
    assert f"  derive    {DEFTERM}: 1 document(s), " in shown, shown[-3000:]
    assert f"  derive    {XREF}: 1 document(s), " in shown, shown[-3000:]
    store = project / ".omniweave" / "docs.owstore"

    assert _rows(
        store,
        "SELECT operator, driver, decision_id IS NULL, cost_class, status FROM work "
        "WHERE operator LIKE 'derive.%' AND operator <> 'derive.segment' ORDER BY 1",
    ) == [
        ("derive.anchor", DEFTERM, 1, "free", "done"),
        ("derive.xref", XREF, 1, "free", "done"),
    ]
    assert _rows(store, "SELECT pass_id, cost_rank, phase, lanes FROM derive_pass ORDER BY 1") == [
        (DEFTERM, 0, 30, '["anchor","entity"]'),
        (XREF, 0, 30, '["xref"]'),
    ]
    live = _rows(store, "SELECT segment_id FROM segment WHERE state = 0 ORDER BY 1")
    runs = _rows(store, "SELECT pass_id, segment_id FROM derive_run")
    for pass_id in (DEFTERM, XREF):
        assert sorted((s,) for p, s in runs if p == pass_id) == live, pass_id
    assert _rows(store, "SELECT lane, count(*) FROM derive_cover GROUP BY 1 ORDER BY 1") == [
        ("anchor", len(live)),
        ("entity", len(live)),
        ("xref", len(live)),
    ]
    anchors = sorted(
        str(name)
        for (name,) in _rows(store, "SELECT name_norm FROM anchor WHERE akind = 'defined_term'")
    )
    assert anchors == ["business_day", "company", "ibm", "lender"]
    assert ("International Business Machines Corporation", "expansion") in _rows(
        store, "SELECT surface, alias_kind FROM entity_alias"
    )
    assert _rows(
        store, "SELECT DISTINCT origin_operator, origin_driver FROM derive_run ORDER BY 1"
    ) == [("derive.anchor", DEFTERM), ("derive.xref", XREF)]
    sites = _rows(store, "SELECT akind, name_norm, surface FROM ref_site ORDER BY 1, 2")
    assert sites == [
        ("exhibit", "1", "Schedule 1"),
        ("identifier", "gl_4471", "GL-4471"),
        ("section", "1", "Section 1"),
    ]
    assert _rows(store, "SELECT count(*) FROM ref_unresolved") == [(len(sites),)]

    before = _rows(store, "SELECT run_id FROM derive_run ORDER BY 1")
    code, shown = _run(project, env, "add", "docs")
    assert code == 0, shown[-3000:]
    assert "  derive    " not in shown, "an unchanged corpus derives nothing"
    assert _rows(store, "SELECT run_id FROM derive_run ORDER BY 1") == before
