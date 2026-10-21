"""A file edited in place and added again: the same document at its next generation. D905.

`0001_init.sql:150` made `doc_key` *"sha256(NORMALIZED source bytes)[:16]"*, so an edit hashed to a
new key and opened a second `doc` row under a new `doc_ord`; D645 retired the first, and every cite
into it died with it, the unchanged blocks' included (D880, D882 pinned exactly that). A user
ruling of 2026-10-19 (D40's option a) moved identity to the file's place in its corpus
(`identity.location_key`): the edit is the same `doc_ord` at `gen = 2`, and `rebind()` carries
every block whose content did not move, as 03:1340-1364's worked example always showed.

These tests read the live set the way the store defines it, `block.state = 0` on a document with no
retirement marker. Real `python -m omniweave add` children over text files, so the conform tier
(Q-G25).
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
KEPT = "Each party bears its own costs."
FIRST = f"{KEPT}\n\nThe indemnity cap is two million euros.\n"
EDITED = f"{KEPT}\n\nThe indemnity cap is five million euros.\n"
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
    """Each `doc` row whose uri ends in `name`: ordinal, generation, retirement, texts, cites."""
    connection = sqlite3.connect(project / ".omniweave" / "docs.owstore")
    try:
        out: list[dict[str, object]] = []
        rows = connection.execute(
            "SELECT doc_ord, gen, uri, x FROM doc ORDER BY doc_ord"
        ).fetchall()
        for doc_ord, gen, uri, x in rows:
            if not str(uri).endswith("/" + name):
                continue
            blocks = connection.execute(
                "SELECT state, text, cite FROM block WHERE doc_ord = ? AND text IS NOT NULL",
                (doc_ord,),
            ).fetchall()
            out.append(
                {
                    "doc_ord": doc_ord,
                    "gen": gen,
                    "retired": json.loads(x or "{}").get(RETIRED),
                    "live": " ".join(str(t) for s, t, _ in blocks if s == 0),
                    "other": " ".join(str(t) for s, t, _ in blocks if s != 0),
                    "cites": {str(t): str(c) for s, t, c in blocks if s == 0},
                }
            )
        return out
    finally:
        connection.close()


def _added(project: Path) -> None:
    done = _add(project)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-1200:]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_bytes(PROJECT.encode("utf-8"))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "cap.txt").write_bytes(FIRST.encode("utf-8"))
    (tmp_path / "docs" / "other.txt").write_bytes(b"An unrelated note.\n")
    _added(tmp_path)
    return tmp_path


def test_an_identical_re_add_is_the_same_document(project: Path) -> None:
    before = _docs(project, "cap.txt")
    _added(project)
    assert _docs(project, "cap.txt") == before
    [only] = before
    assert only["retired"] is None and "two million" in str(only["live"])


def test_an_edit_is_the_same_document_at_its_next_generation(project: Path) -> None:
    """D905: one row, the same `doc_ord`, `gen` moved on, and only the new text is live."""
    [before] = _docs(project, "cap.txt")
    (project / "docs" / "cap.txt").write_bytes(EDITED.encode("utf-8"))
    _added(project)
    [after] = _docs(project, "cap.txt")
    assert after["doc_ord"] == before["doc_ord"]
    assert int(str(after["gen"])) > int(str(before["gen"]))
    assert after["retired"] is None
    assert "five million" in str(after["live"]) and "two million" not in str(after["live"])


def test_an_unchanged_paragraph_keeps_its_cite_across_the_edit(project: Path) -> None:
    """D40, resolved: `rebind()` carries the block whose content did not move, so a cite handed
    out before the edit still names live text after it."""
    [before] = _docs(project, "cap.txt")
    cites = before["cites"]
    assert isinstance(cites, dict)
    kept = cites[KEPT]
    (project / "docs" / "cap.txt").write_bytes(EDITED.encode("utf-8"))
    _added(project)
    [after] = _docs(project, "cap.txt")
    assert isinstance(after["cites"], dict)
    assert after["cites"][KEPT] == kept


def test_two_files_holding_the_same_bytes_are_two_documents(project: Path) -> None:
    """D905: a document is its place, so a copy is another document and each keeps its own."""
    (project / "docs" / "copy.txt").write_bytes(FIRST.encode("utf-8"))
    _added(project)
    [original] = _docs(project, "cap.txt")
    [copy] = _docs(project, "copy.txt")
    assert original["doc_ord"] != copy["doc_ord"]
    assert original["live"] == copy["live"]


def test_a_renamed_file_keeps_its_document_and_every_cite(project: Path) -> None:
    """D905: a file whose old place is gone and whose bytes now stand at a new one moved; its
    document takes the new place, so search holds one copy and every cite carries."""
    [before] = _docs(project, "cap.txt")
    (project / "docs" / "cap.txt").rename(project / "docs" / "renamed.txt")
    _added(project)
    assert _docs(project, "cap.txt") == []
    [after] = _docs(project, "renamed.txt")
    assert after["doc_ord"] == before["doc_ord"]
    assert after["cites"] == before["cites"]
    assert after["live"] == before["live"]
