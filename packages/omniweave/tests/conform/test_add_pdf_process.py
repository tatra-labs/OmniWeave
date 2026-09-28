"""`python -m omniweave add` then `query` over a born-digital PDF, as real children (D628).

Until D628 no PDF had been routed: `decode.pdf-text-layer` defers on `decode.char_count`, and
nothing computed it (D579). This is the whole path that now runs -- the pdfium signal child at
routing, the S4 worker at parse, the glyph origins, quads and retained part at decode -- and the
cite `ow query` returns from it. It needs the three `[drivers]` opt-ins a checkout needs (D576).
"""

from __future__ import annotations

import os
import shutil
import sqlite3  # noqa: TID251 -- the assertions read the store the children wrote.
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import Captured, run_captured

pytestmark = pytest.mark.conform

TIMEOUT_S = 180
PDF_FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-pdf" / "fixtures"
PROJECT = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)


def _ow(project: Path, *args: str) -> Captured:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return run_captured(
        (sys.executable, "-m", "omniweave", *args),
        stdin=b"",
        cwd=str(project),
        env={**keep, "OMNIWEAVE_HOME": str(project / "owhome")},
        timeout_s=TIMEOUT_S,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    shutil.copy(PDF_FIXTURES / "gen02p.pdf", docs / "contract.pdf")
    shutil.copy(PDF_FIXTURES / "no_text_layer.pdf", docs / "scan.pdf")
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    return tmp_path


def _rows(project: Path, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(project / ".omniweave" / "index.owstore")
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_ow_add_routes_parses_and_retains_a_pdf_and_ow_query_cites_it_verbatim(
    project: Path,
) -> None:
    added = _ow(project, "add", "docs")
    progress = added.stderr.decode("utf-8", "replace")
    assert added.returncode == 0, progress
    assert "  route     1 planned (parse.pdf.pdfium 1); 0 refused" in progress, progress
    assert "  parse     1 parsed (parse.pdf.pdfium 1), 1 documents" in progress, progress
    #  The scanned page's `ink.tiles` has no computer: it is held, never refused (D579, D628).
    assert "deferred (decode.blank-part-escape): ink.tiles:" in progress, progress
    #  Two children for the clean PDF (GATE, DECODE free); three for the scan (and LOCAL).
    assert "  route     5 signal children (pdfium 5)" in progress, progress

    assert _rows(project, "SELECT path, store_ref IS NOT NULL FROM part") == [("pdf/source.pdf", 1)]
    assert _rows(project, "SELECT count(*) FROM block WHERE quad IS NULL AND parent_id IS NOT NULL "
                          "AND text IS NOT NULL") == [(0,)]  # fmt: skip
    assert _rows(project, "SELECT state FROM unit WHERE unit_uri LIKE '%scan.pdf'") == [
        ("identified",)
    ]

    asked = _ow(project, "query", "severance")
    answer = asked.stdout.decode("utf-8")
    assert asked.returncode == 0, asked.stderr.decode("utf-8", "replace")
    assert "contract.pdf p.0 · verbatim" in answer, answer
