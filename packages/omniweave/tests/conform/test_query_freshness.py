"""D647 end to end: a query names a file edited or removed since the last ingest, and its fix works.

D645 made `ow add` and `ow ingest` read an edited file again. Between the edit and that run, a
query read the old text with no gate. Now the query `stat`s the indexed files in scope:

- edited after `ow add`, with no ingest since: the answer is `degraded` by gate 6, which names the
  file and prints `ow add <path>`; running it makes the answer whole again;
- removed: gate 6 says the file is no longer at its path, and prints `ow ingest`.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import Captured, run_captured

pytestmark = pytest.mark.conform

PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
TIMEOUT_S = 300


def _run(project: Path, env: dict[str, str], *argv: str) -> Captured:
    return run_captured(
        (sys.executable, "-m", "omniweave", *argv),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=TIMEOUT_S,
    )


def _answer(project: Path, env: dict[str, str], question: str) -> dict[str, object]:
    done = _run(project, env, "query", question, "--render", "json")
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-3000:]
    return json.loads(done.stdout)


def _gates(answer: dict[str, object]) -> str:
    return next(value for key, value in answer["trailer_extra"] if key == "verdict.gates")  # type: ignore[union-attr]


def test_a_query_names_a_file_edited_or_removed_since_the_last_ingest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    note = project / "docs" / "note.md"
    note.write_text("# Launch\n\nThe launch code is AARDVARK.\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    env = {
        **keep,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(tmp_path / "ow"),
    }
    added = _run(project, env, "add", "docs")
    assert added.returncode == 0, added.stderr.decode("utf-8", "replace")[-3000:]
    assert _gates(_answer(project, env, "launch code")) == "[]"

    #  1. Edited, and no ingest since: the old text still answers, and now says so.
    note.write_text("# Launch\n\nThe launch code is ZEBRAFISH now.\n", encoding="utf-8")
    answer = _answer(project, env, "launch code")
    assert _gates(answer) == "[source_edited_unindexed]"
    (line,) = answer["blocking"]  # type: ignore[misc]
    assert "note.md changed since it was indexed" in line
    fix = re.search(r"Fix: `(ow add .+?)`", line)
    assert fix is not None, line

    #  2. The fix it printed, run: the new text answers and nothing is blocking.
    ran = _run(project, env, *shlex.split(fix.group(1))[1:])
    assert ran.returncode == 0, ran.stderr.decode("utf-8", "replace")[-3000:]
    answer = _answer(project, env, "ZEBRAFISH")
    assert _gates(answer) == "[]"
    assert any("ZEBRAFISH" in str(hit["text"]) for hit in answer["evidence"])  # type: ignore[union-attr]

    #  3. Removed: named as gone, with the ingest that sweeps it.
    note.unlink()
    (line,) = _answer(project, env, "ZEBRAFISH")["blocking"]  # type: ignore[misc]
    assert "note.md is no longer at its path since it was indexed" in line
    assert "Fix: `ow ingest`" in line
