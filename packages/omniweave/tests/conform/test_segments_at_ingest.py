"""D665 end to end: `ow add` segments what it parses, in the same drain, and the Segments verify.

Five text fixtures through a real `ow add`: each settles, each earns one `derive.segment` row in the
transaction that settled it, the drain claims those rows, a real worker runs the discovered
segmenter over each document's view, and `segment`/`segment_block` hold every text block of every
document exactly once -- with `ow store verify`'s digest clause clean. A second `ow add` over the
same files parses nothing and segments nothing.
"""

from __future__ import annotations

import os
import shutil
import sqlite3  # noqa: TID251 -- the assertions read the store the run wrote.
import sys
from pathlib import Path
from typing import cast

import pytest
from omniweave_core.host.subproc import run_captured
from omniweave_core.store import sqlite as ow
from omniweave_core.store.verify import verify_store

pytestmark = pytest.mark.conform

FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-office" / "fixtures" / "text"
PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
FILES = ("guide.md", "notes.txt", "page.html", "data.json", "analysis.ipynb")
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


def test_an_add_segments_every_document_it_parses_and_the_segments_verify(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    for name in FILES:
        shutil.copyfile(FIXTURES / name, project / "docs" / name)
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
    assert "5 parsed (parse.text.builtin 5)" in shown, shown[-3000:]
    assert "  segment   5 document(s): " in shown, shown[-3000:]
    store = project / ".omniweave" / "docs.owstore"

    assert _rows(
        store,
        "SELECT operator, driver, decision_id IS NULL, status, count(*) FROM work "
        "WHERE operator = 'derive.segment' GROUP BY 1, 2, 3, 4",
    ) == [("derive.segment", "derive.segment.spine", 1, "done", 5)]
    per_doc = {
        str(uri): int(cast("int", n))
        for uri, n in _rows(
            store,
            "SELECT d.uri, count(s.segment_id) FROM doc d "
            "LEFT JOIN ow_segment_head s ON s.doc_ord = d.doc_ord GROUP BY d.uri",
        )
    }
    assert len(per_doc) == 5
    assert all(n >= 1 for n in per_doc.values()), per_doc
    text_blocks = _rows(store, "SELECT count(*) FROM ow_block_head WHERE text IS NOT NULL")
    members = _rows(store, "SELECT count(*) FROM segment_block")
    assert members == text_blocks, "every text block is a member of exactly one Segment"

    connection = ow.connect(store)
    try:
        report = verify_store(connection, now_ns=0, clauses=["segment_digest"])
    finally:
        connection.close()
    [clause] = report.clauses
    assert not clause.findings, clause.findings
    assert clause.checked == sum(per_doc.values())

    before = _rows(store, "SELECT segment_id, content_digest FROM segment ORDER BY segment_id")
    code, shown = _run(project, env, "add", "docs")
    assert code == 0, shown[-3000:]
    assert "  segment   " not in shown, "an unchanged corpus parses and segments nothing"
    assert (
        _rows(store, "SELECT segment_id, content_digest FROM segment ORDER BY segment_id") == before
    )
