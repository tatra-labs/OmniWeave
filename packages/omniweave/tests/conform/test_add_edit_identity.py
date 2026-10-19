"""A file edited in place and added again: one document, or two? Ledger D40, pinned. D880.

`0001_init.sql:150` makes `doc_key` *"sha256(NORMALIZED source bytes)[:16]"* and `:158` keeps *"one
doc row per `doc_key`"*, so an edit hashes to a new key and `begin_doc` opens a second `doc` row
at `gen = 1`. `03:1340-1364`'s worked example re-parses the same `doc_ord` at `gen = 2` instead.
D40 recorded at P2 that both cannot hold and that no plan line says which identity survives an
edit. It needs a ruling, and none was made.

These are real `python -m omniweave add` children over two text files, so this is the conform tier
(Q-G25). The first test holds what the content hash does promise (*"the `doc_key` recipe that
makes an identical re-run the same document"*, 03:462). The second pins the edit case AS IT IS:
two `doc` rows for one uri, the old text still live beside the new. That is the defect, asserted
exactly rather than marked `xfail`, because an `xfail` also absorbs a failure in setup and so
could not tell this defect from a broken fixture (its first draft did exactly that). When D40 is
ruled and built, this test fails, and whoever fixes it rewrites it as 03's worked example and
G19's full rebuild read the case: one document per uri, holding only the new text.
"""

from __future__ import annotations

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


def _add(project: Path) -> Captured:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return run_captured(
        (sys.executable, "-m", "omniweave", "add", "docs", "--quiet"),
        stdin=b"",
        cwd=str(project),
        env={**keep, "OMNIWEAVE_HOME": str(project / "owhome")},
        timeout_s=TIMEOUT_S,
    )


def _rows(project: Path) -> list[tuple[str, str]]:
    """`(uri's file name, every block's text joined)` per `doc` row, in `doc_ord` order."""
    connection = sqlite3.connect(project / ".omniweave" / "docs.owstore")
    try:
        docs = connection.execute("SELECT doc_ord, uri FROM doc ORDER BY doc_ord").fetchall()
        return [
            (
                str(uri).rsplit("/", 1)[-1],
                " ".join(
                    str(text)
                    for (text,) in connection.execute(
                        "SELECT text FROM block WHERE doc_ord = ? AND text IS NOT NULL "
                        "ORDER BY block_id",
                        (doc_ord,),
                    )
                ),
            )
            for doc_ord, uri in docs
        ]
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
    before = _rows(project)
    again = _add(project)
    assert again.returncode == 0, again.stderr.decode("utf-8", "replace")[-1200:]
    assert _rows(project) == before
    assert sorted(name for name, _ in before) == ["cap.txt", "other.txt"]


def test_an_edited_file_added_again_is_two_documents_today_d40(project: Path) -> None:
    """THE DEFECT, pinned: the old version stays live under the same uri (ledger D40)."""
    (project / "docs" / "cap.txt").write_text(EDITED, encoding="utf-8")
    again = _add(project)
    assert again.returncode == 0, again.stderr.decode("utf-8", "replace")[-1200:]
    caps = [text for name, text in _rows(project) if name == "cap.txt"]
    assert len(caps) == 2, f"D40 resolved? {len(caps)} doc row(s) for one uri: {caps}"
    assert "two million" in caps[0] and "five million" in caps[1]
