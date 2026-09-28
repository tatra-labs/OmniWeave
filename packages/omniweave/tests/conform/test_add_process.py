"""`python -m omniweave add` then `python -m omniweave query`, as real children with piped stdio.

V01-15's path without its first and last terms: `ow add <dir>` then `ow query "<question>"`,
answering with a `cite` from the document the add parsed. `ow install` is not on it because the
two verbs need no host wiring, and the clean machine and the hundred documents are W7.7c's and
D602's. The add parses a real DOCX, so it starts the S4 worker, and that is why this is `conform`
(13-quality.md section 2.7). It needs the three `[drivers]` opt-ins a checkout needs (D576).

The directory is named in CJK, which a cp1252 pipe cannot carry. The report prints the path of
every pending unit and the uri of every completed one, so without `__main__`'s UTF-8 reconfigure
(10:1553-1561) this child would die mid-report on Windows (D431). The child runs without
`PYTHONUTF8` and `PYTHONIOENCODING`, as `test_query_process.py`'s do.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from omniweave_core.host.subproc import Captured, run_captured

pytestmark = pytest.mark.conform

TIMEOUT_S = 120
CJK = "契約"
OFFICE_FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-office" / "fixtures"
SCHEMA = Path(__file__).resolve().parents[4] / "schema" / "add-out-v1.json"
PROJECT = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)


def _env(home: Path) -> dict[str, str]:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return {**keep, "OMNIWEAVE_HOME": str(home)}


def _ow(project: Path, *args: str) -> Captured:
    return run_captured(
        (sys.executable, "-m", "omniweave", *args),
        stdin=b"",
        cwd=str(project),
        env=_env(project / "owhome"),
        timeout_s=TIMEOUT_S,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    docs = tmp_path / CJK
    docs.mkdir()
    shutil.copy(OFFICE_FIXTURES / "rich.docx", docs / "rich.docx")
    (docs / "notes.txt").write_text("Routed to no driver.", encoding="utf-8")
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    return tmp_path


def test_ow_add_parses_a_docx_and_ow_query_cites_it(project: Path) -> None:
    added = _ow(project, "add", CJK)
    assert added.returncode == 0, added.stderr.decode("utf-8", "replace")
    lines = added.stdout.decode("utf-8").splitlines()
    assert lines[0].endswith("  ·  discovered 2  ·  unchanged 0  ·  queued 2  ·  skipped 0")
    assert lines[1].rstrip("\r") == "completed 1   pending 1 (1 no_driver)   deadline_reached false"
    assert any(f"{CJK}/notes.txt  no_driver" in line for line in lines), lines
    progress = added.stderr.decode("utf-8")
    assert "  parse     1 parsed (parse.office.anydoc 1), 1 documents" in progress, progress

    asked = _ow(project, "query", "quarterly report")
    assert asked.returncode == 0, asked.stderr.decode("utf-8", "replace")
    answer = asked.stdout.decode("utf-8")
    assert "| d1#2 | rich.docx |" in answer, answer
    assert "Quarterly report" in answer


def test_ow_add_under_render_json_reports_the_completed_document(project: Path) -> None:
    added = _ow(project, "add", CJK, "--render", "json")
    assert added.returncode == 0, added.stderr.decode("utf-8", "replace")
    document: dict[str, Any] = json.loads(added.stdout.decode("utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    #  D555: `scope_id` is the store's text prefix, `ow_add`'s own deviation; the rest validates.
    Draft202012Validator(schema).validate({**document, "scope_id": 0})
    (completed,) = document["completed"]
    assert completed["uri"].endswith(f"/{CJK}/rich.docx")
    assert (completed["doc_ord"], completed["gen"]) == (1, 1)
    assert completed["blocks"] > 0
    (pending,) = document["pending"]
    assert pending["uri"].endswith(f"/{CJK}/notes.txt")
    assert pending["reason"] == "no_driver"
