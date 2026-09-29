"""`ow ingest --accept-partial`, end to end: the escape `unit.corrupt`'s false positive needs.

05:2240 names the false positive in as many words: *"a PDF with a broken xref that pdfium
reconstructs successfully is refused here and would have parsed. The escape is `ow add
--accept-partial`"*. The fixture is `omniweave-pdf`'s own two-page PDF with 2,000 bytes after its
`%%EOF`, which puts the `%%EOF` outside the window a reader searches, so the structural check
fails and pdfium still reads it. Through real children:

1. `ow add` refuses it at `gate.corrupt`, and `ow query` is `degraded` by gate 9 naming
   `OW_MALFORMED`, the check that failed and the override (05:3035);
2. `ow ingest --accept-partial <path>` reads it again unchanged (D641's re-open), and pdfium
   parses it;
3. `ow query` no longer fires gate 9.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

FIXTURE = Path(__file__).resolve().parents[3] / "omniweave-pdf" / "fixtures" / "gen02p.pdf"
PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
TIMEOUT_S = 300


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
    return done.stdout.decode("utf-8", "replace")


def _gates(project: Path, env: dict[str, str]) -> tuple[list[str], list[str]]:
    answer = json.loads(_ow(project, env, "query", "page", "--render", "json"))
    shown = next(value for key, value in answer["trailer_extra"] if key == "verdict.gates")
    gates = [gate for gate in shown.strip("[]").replace(" ", "").split(",") if gate]
    return gates, answer["blocking"]


def test_a_padded_pdf_is_refused_and_accept_partial_lets_pdfium_read_it(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    padded = project / "docs" / "padded.pdf"
    padded.write_bytes(FIXTURE.read_bytes() + b" " * 2000)
    home = tmp_path / "home"
    home.mkdir()
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    env = {
        **keep,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(tmp_path / "ow"),
    }

    _ow(project, env, "add", "docs")
    gates, blocking = _gates(project, env)
    assert gates == ["parse_gap_in_scope"]
    (line,) = blocking
    assert "OW_MALFORMED" in line
    assert "no %%EOF in the last 1024 bytes" in line
    assert "ow ingest --accept-partial" in line

    ingested = _ow(project, env, "ingest", "--accept-partial", str(padded))
    assert "parse.pdf.pdfium 1" in ingested
    gates, blocking = _gates(project, env)
    assert "parse_gap_in_scope" not in gates, blocking
