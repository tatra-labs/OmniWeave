"""D644 end to end: a PDF above `[ingest] max_parts` is named with the value that admits it, and
read once the cap is raised.

Two files through a real `ow ingest`, `ow add` and `ow query`, under `[ingest] max_parts = 4`:

- `long.pdf` is `omniweave-pdf`'s `gen02p.pdf` padded to five pages by the paired-damage kit's
  `pdfpages`. `gate.too-many-parts` refuses it on `pdfium`'s page count (05:3037), and gate 9 names
  `OW_RESOURCE_LIMIT`, the count, the cap it was read under, and the `max_parts` line that admits
  it. Its fix, run before the cap moves, reads nothing: the refusal is the cap's, and the file did
  not change. Raising the cap the way the detail says, then running the same fix, reads it.
- `short.pdf` is `gen01p.pdf`, under the cap, and read by the first run as any PDF is.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3  # noqa: TID251 -- the assertions read the store the run wrote.
import sys
from pathlib import Path

import pytest
from omniweave_conform.pdfpages import pad_pages, page_count
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-pdf" / "fixtures"
PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
    "[ingest]\nmax_parts = 4\n"
)
TIMEOUT_S = 300
QUESTION = "schedule severance"


def _ow(project: Path, env: dict[str, str], *argv: str) -> str:
    done = run_captured(
        (sys.executable, "-m", "omniweave", *argv),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=TIMEOUT_S,
    )
    shown = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert done.returncode == 0, shown[-3000:]
    return shown


def _answer(project: Path, env: dict[str, str]) -> dict[str, object]:
    done = run_captured(
        (sys.executable, "-m", "omniweave", "query", QUESTION, "--render", "json"),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=TIMEOUT_S,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-3000:]
    return json.loads(done.stdout)


def _gates(answer: dict[str, object]) -> str:
    return next(value for key, value in answer["trailer_extra"] if key == "verdict.gates")  # type: ignore[union-attr]


def test_a_pdf_above_max_parts_is_named_and_read_once_the_cap_is_raised(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    long_pdf = pad_pages((FIXTURES / "gen02p.pdf").read_bytes(), to_pages=5)
    assert page_count(long_pdf) == 5
    (project / "docs" / "long.pdf").write_bytes(long_pdf)
    (project / "docs" / "short.pdf").write_bytes((FIXTURES / "gen01p.pdf").read_bytes())
    home = tmp_path / "home"
    home.mkdir()
    keep = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONUTF8", "PYTHONIOENCODING"} and not k.startswith("OMNIWEAVE_INGEST_")
    }
    env = {
        **keep,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(tmp_path / "ow"),
    }

    #  1. Under the cap of four: the five-page file is refused, and the refusal says by how much.
    ingested = _ow(project, env, "ingest", "docs")
    assert "1 refused (gate.too-many-parts 1)" in ingested
    assert "parse     1 parsed (parse.pdf.pdfium 1)" in ingested
    answer = _answer(project, env)
    assert _gates(answer) == "[parse_gap_in_scope]"
    (line,) = answer["blocking"]  # type: ignore[misc]
    assert "long.pdf: refused as resource_limit" in line
    assert "OW_RESOURCE_LIMIT" in line
    assert "it has 5 parts, and [ingest] max_parts was 4 when it was read" in line
    assert "or set OMNIWEAVE_INGEST_MAX_PARTS=5" in line
    assert {hit["doc_uri"] for hit in answer["evidence"]} == {"short.pdf"}  # type: ignore[union-attr]
    fix = re.search(r"Fix: `(ow add .+?)`", line)
    raise_to = re.search(r"`(max_parts = \d+)` under \[ingest\] in omniweave.toml", line)
    assert fix is not None and raise_to is not None, line

    #  2. The fix before the cap moves: the file did not change, so nothing is read again.
    _ow(project, env, *shlex.split(fix.group(1))[1:])
    assert _gates(_answer(project, env)) == "[parse_gap_in_scope]"

    #  3. What the refusal says, done: the line in omniweave.toml; then the same fix.
    toml = (project / "omniweave.toml").read_text(encoding="utf-8")
    (project / "omniweave.toml").write_text(
        toml.replace("max_parts = 4", raise_to.group(1)), encoding="utf-8"
    )
    opened = _ow(project, env, *shlex.split(fix.group(1))[1:])
    assert "route     1 planned (parse.pdf.pdfium 1); 0 refused" in opened

    answer = _answer(project, env)
    assert _gates(answer) == "[]"
    assert answer["blocking"] == []
    assert "long.pdf" in {hit["doc_uri"] for hit in answer["evidence"]}  # type: ignore[union-attr]
    connection = sqlite3.connect(project / ".omniweave" / "docs.owstore")
    try:
        pages = dict(
            connection.execute(
                "SELECT substr(doc.uri, -9), count(DISTINCT block.page) FROM block "
                "JOIN doc ON doc.doc_ord = block.doc_ord GROUP BY doc.uri"
            ).fetchall()
        )
    finally:
        connection.close()
    assert pages == {"/long.pdf": 5, "short.pdf": 1}
