"""ADR-15 end to end: a PDF needing a password is named, is opened once one is given, and an
owner-only one is read with none.

Two files through a real `ow ingest`, `ow add` and `ow query`, both encrypted by the paired-damage
kit's `pdfcrypt` from `omniweave-pdf`'s own fixtures:

- `locked.pdf` has a user password. The pdfium child cannot open it with the empty password and
  answers `unit.encrypted = true`, `gate.encrypted` refuses it, and gate 9 names `OW_ENCRYPTED`
  with the commands that supply one on this machine (D15.5). A wrong password leaves it refused,
  and the report says where the name resolved from. Doing what the refusal says -- an
  `OW_SECRET_*` variable and a `password_file` line -- and running its fix opens it (D15.3, D15.4).
- `restricted.pdf` has only an owner password: `/Encrypt`, print and copy denied, and readable with
  none. 05:2239 read literally would refuse it; D15.2 reads it, as the build always had.

**The password is nowhere on disk afterwards.** Every file under the project -- the store, its WAL,
the CAS, the run manifests, the cache's scratch -- is searched for its bytes, and the one file
that holds it, `passwords.toml`, holds the name and not the secret (05:474-476).
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
USER, OWNER = "ow-t3-9f2c7e", "ow-t3-owner"
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


def test_a_locked_pdf_is_named_opened_once_its_password_is_given_and_a_restricted_one_is_read(
    tmp_path: Path,
) -> None:
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
    keep = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONUTF8", "PYTHONIOENCODING"} and not k.startswith("OW_SECRET_")
    }
    env = {
        **keep,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(tmp_path / "ow"),
    }

    #  1. No password anywhere: the locked file is refused, and the refusal says how to fix it.
    ingested = _ow(project, env, "ingest", "docs")
    assert "1 refused (gate.encrypted 1)" in ingested
    assert "parse     1 parsed (parse.pdf.pdfium 1)" in ingested
    answer = _answer(project, env)
    assert _gates(answer) == "[parse_gap_in_scope]"
    (line,) = answer["blocking"]  # type: ignore[misc]
    assert "locked.pdf: refused as encrypted" in line
    assert "OW_ENCRYPTED" in line
    assert "(or set OW_SECRET_LOCKED where there is no keystore)" in line
    assert {hit["doc_uri"] for hit in answer["evidence"]} == {"restricted.pdf"}  # type: ignore[union-attr]

    #  2. A wrong password, for one run: still refused, and the report says where it came from.
    (project / "wrong.toml").write_text('"docs/locked.pdf" = "wrong"\n', encoding="utf-8")
    wrong = _ow(
        project,
        {**env, "OW_SECRET_WRONG": "not-it"},
        "ingest",
        "docs",
        "--password-file",
        "wrong.toml",
    )
    assert "1 refused (gate.encrypted 1)" in wrong
    assert "password  1 resolved: wrong from the environment variable OW_SECRET_WRONG" in wrong

    #  3. What the refusal says, done: the variable, the line, the key; then the fix it names.
    mapped = re.search(r"add the line `(.+?)` to the password file", line)
    fix = re.search(r"Fix: `(ow add .+?)`", line)
    assert mapped is not None and fix is not None, line
    (project / "passwords.toml").write_text(mapped.group(1) + "\n", encoding="utf-8")
    with (project / "omniweave.toml").open("a", encoding="utf-8") as handle:
        handle.write('[ingest]\npassword_file = "passwords.toml"\n')
    opened = _ow(project, {**env, "OW_SECRET_LOCKED": USER}, *shlex.split(fix.group(1))[1:])
    assert "route     1 planned (parse.pdf.pdfium 1); 0 refused" in opened
    assert "password  1 resolved: locked from the environment variable OW_SECRET_LOCKED" in opened

    answer = _answer(project, env)
    assert _gates(answer) == "[]"
    assert answer["blocking"] == []
    assert "locked.pdf" in {hit["doc_uri"] for hit in answer["evidence"]}  # type: ignore[union-attr]
    connection = sqlite3.connect(project / ".omniweave" / "docs.owstore")
    try:
        docs = dict(connection.execute("SELECT substr(uri, -12), x FROM doc").fetchall())
        diags = connection.execute("SELECT code, page FROM diag").fetchall()
    finally:
        connection.close()
    assert json.loads(docs["s/locked.pdf"]) == {"x.ow.decrypted": True}
    assert json.loads(docs["stricted.pdf"]) == {}
    assert diags == [("OW_DOC_DECRYPTED", 0)]

    #  4. Nothing the build wrote holds the password: not the store, not a manifest, not scratch.
    secret = USER.encode("utf-8")
    holding = [
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.is_file() and secret in path.read_bytes()
    ]
    assert holding == []
    assert not list(project.rglob(".omniweave-password"))
