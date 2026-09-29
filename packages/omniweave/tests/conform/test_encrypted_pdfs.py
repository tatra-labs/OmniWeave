"""ADR-15 D15.1-D15.2 end to end: a PDF needing a password is named; one that does not is read.

Two files through a real `ow add` and a real `ow query`, both encrypted by the paired-damage kit's
`pdfcrypt` from `omniweave-pdf`'s own fixtures:

- `locked.pdf` has a user password. Detection's trailer scan finds `/Encrypt`, the pdfium child
  cannot open it with the empty password and answers `unit.encrypted = true`, `gate.encrypted`
  refuses it, and gate 9 names `OW_ENCRYPTED` with no fix, because D15.3's password path is not
  built. Before ADR-15 it was held for ever under gate 5's *"run ow ingest"*.
- `restricted.pdf` has only an owner password: `/Encrypt`, print and copy denied, and readable with
  none. 05:2239 read literally would refuse it; D15.2 reads it, as the build always had.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from omniweave_conform.pdfcrypt import encrypt_pdf
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-pdf" / "fixtures"
PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
TIMEOUT_S = 300
USER, OWNER = "u", "o"


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


def test_a_pdf_needing_a_password_is_named_and_an_owner_only_one_is_read(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    (project / "docs" / "locked.pdf").write_bytes(
        encrypt_pdf(
            (FIXTURES / "gen02p.pdf").read_bytes(), user_password=USER, owner_password=OWNER
        )
    )
    (project / "docs" / "restricted.pdf").write_bytes(
        encrypt_pdf((FIXTURES / "gen01p.pdf").read_bytes(), user_password="", owner_password=OWNER)
    )
    home = tmp_path / "home"
    home.mkdir()
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    env = {
        **keep,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(tmp_path / "ow"),
    }

    ingested = _ow(project, env, "ingest", "docs")
    assert "1 refused (gate.encrypted 1)" in ingested
    assert "parse     1 parsed (parse.pdf.pdfium 1)" in ingested

    answer = json.loads(_ow(project, env, "query", "schedule severance", "--render", "json"))
    gates = next(value for key, value in answer["trailer_extra"] if key == "verdict.gates")
    assert gates == "[parse_gap_in_scope]"
    (line,) = answer["blocking"]
    assert "locked.pdf: refused as encrypted" in line
    assert "OW_ENCRYPTED" in line
    assert "this build reads none yet" in line
    assert "Fix:" not in line
    assert {hit["doc_uri"] for hit in answer["evidence"]} == {"restricted.pdf"}
