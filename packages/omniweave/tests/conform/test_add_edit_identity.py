"""A file edited in place and added again: what the store keeps, and what it serves. D880, D882.

`0001_init.sql:150` makes `doc_key` *"sha256(NORMALIZED source bytes)[:16]"* and `:158` keeps *"one
doc row per `doc_key`"*, so an edit hashes to a new key and `begin_doc` opens a second `doc` row
at `gen = 1`, under a new `doc_ord`. D645 then retires the first: `discover.REPLACED_SCAN_SQL`
names a document whose file now holds other bytes, its blocks leave `state = 0`, it carries
`x.ow.retired = {"reason": "source_deleted"}`, and `block_history` records each block. So the
store serves the new text only.

What D40 (P2) still leaves open is narrower than D880 first reported: 03:1340-1364's worked example
re-parses the SAME `doc_ord` at `gen = 2`, so `rebind()` carries every unchanged cite. Under the
content-hash key, an edit retires the old document's cites and mints new ones under a new
`doc_ord`. Which of the two a citation should survive is the ruling owed.

**D882's correction.** D880's first version of this file read every block regardless of `state`
and reported both versions as live. They are not: the old version is retired, as above. These
tests read the live set the way the store defines it, `block.state = 0` on a document with no
retirement marker, and pin each half of the behaviour exactly.

Real `python -m omniweave add` children over two text files, so the conform tier (Q-G25).
"""

from __future__ import annotations

import json
import os
import sqlite3  # noqa: TID251 -- the assertions read the store the add wrote.
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import Captured, run_captured

pytestmark = pytest.mark.conform

TIMEOUT_S = 120
PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
FIRST = "The indemnity cap is two million euros.\n"
EDITED = "The indemnity cap is five million euros.\n"
RETIRED = "x.ow.retired"


def _add(project: Path) -> Captured:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return run_captured(
        (sys.executable, "-m", "omniweave", "add", "docs", "--quiet"),
        stdin=b"",
        cwd=str(project),
        env={**keep, "OMNIWEAVE_HOME": str(project / "owhome")},
        timeout_s=TIMEOUT_S,
    )


def _docs(project: Path, name: str) -> list[dict[str, object]]:
    """Each `doc` row whose uri ends in `name`: its ordinal, retirement and texts by state."""
    connection = sqlite3.connect(project / ".omniweave" / "docs.owstore")
    try:
        out: list[dict[str, object]] = []
        rows = connection.execute("SELECT doc_ord, uri, x FROM doc ORDER BY doc_ord").fetchall()
        for doc_ord, uri, x in rows:
            if not str(uri).endswith("/" + name):
                continue
            texts = connection.execute(
                "SELECT state, text FROM block WHERE doc_ord = ? AND text IS NOT NULL",
                (doc_ord,),
            ).fetchall()
            out.append(
                {
                    "doc_ord": doc_ord,
                    "retired": json.loads(x or "{}").get(RETIRED),
                    "live": " ".join(str(t) for s, t in texts if s == 0),
                    "other": " ".join(str(t) for s, t in texts if s != 0),
                }
            )
        return out
    finally:
        connection.close()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "cap.txt").write_text(FIRST, encoding="utf-8")
    (tmp_path / "docs" / "other.txt").write_text("An unrelated note.\n", encoding="utf-8")
    added = _add(tmp_path)
    assert added.returncode == 0, added.stderr.decode("utf-8", "replace")[-1200:]
    return tmp_path


def test_an_identical_re_add_is_the_same_document(project: Path) -> None:
    before = _docs(project, "cap.txt")
    again = _add(project)
    assert again.returncode == 0, again.stderr.decode("utf-8", "replace")[-1200:]
    assert _docs(project, "cap.txt") == before
    [only] = before
    assert only["retired"] is None and "two million" in str(only["live"])


def test_an_edit_retires_the_old_document_and_serves_only_the_new_text(project: Path) -> None:
    """D645, as built: the old row stays, retired, and every block it held leaves the live set."""
    (project / "docs" / "cap.txt").write_text(EDITED, encoding="utf-8")
    again = _add(project)
    assert again.returncode == 0, again.stderr.decode("utf-8", "replace")[-1200:]
    old, new = _docs(project, "cap.txt")
    assert old["retired"] == {"reason": "source_deleted", "gen": 1}
    assert old["live"] == "" and "two million" in str(old["other"])
    assert new["retired"] is None and "five million" in str(new["live"])
    assert "two million" not in str(new["live"])


def test_the_edit_is_a_new_doc_ord_so_no_cite_carries_today_d40(project: Path) -> None:
    """THE OPEN HALF, pinned (D40): 03's worked example keeps the `doc_ord` at `gen = 2`."""
    [before] = _docs(project, "cap.txt")
    (project / "docs" / "cap.txt").write_text(EDITED, encoding="utf-8")
    again = _add(project)
    assert again.returncode == 0, again.stderr.decode("utf-8", "replace")[-1200:]
    old, new = _docs(project, "cap.txt")
    assert old["doc_ord"] == before["doc_ord"]
    assert new["doc_ord"] != old["doc_ord"], "D40 resolved? the edit kept its doc_ord"
