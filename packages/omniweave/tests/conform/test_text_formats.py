"""D646 end to end: Markdown, text, HTML, JSON and a notebook are read, and answer.

Before D646, `decode.text-native` routed these formats to `parse.text.builtin`, which no
distribution shipped, so every one stopped `identified` and gate 5 said *"not indexed yet"* for
ever. Five files through a real `ow add` and `ow query`, the conformance fixtures of
`omniweave-office/fixtures/text`, and each one's own words found.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3  # noqa: TID251 -- the assertions read the store the run wrote.
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-office" / "fixtures" / "text"
PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
TIMEOUT_S = 300
FILES = ("guide.md", "notes.txt", "page.html", "data.json", "analysis.ipynb")


def _run(project: Path, env: dict[str, str], *argv: str) -> tuple[int | None, str]:
    done = run_captured(
        (sys.executable, "-m", "omniweave", *argv),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=TIMEOUT_S,
    )
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")


@pytest.mark.parametrize(
    ("question", "source", "words"),
    [
        ("on-call rota pager", "guide.md", "on-call rota starts in your second week"),
        ("audit launch April", "notes.txt", "audit is not finished"),
        ("uptime feature", "page.html", "Uptime is a feature."),
        ("p99", "page.html", "p99"),  # a page addr by shape, searched once no addr matches (D648)
        ("billing rps limit", "data.json", "limits.rps: 1200"),
        ("churn analysis rate", "analysis.ipynb", "rate = 42 / 1000"),
    ],
)
def test_each_text_format_is_read_and_answers(
    tmp_path_factory: pytest.TempPathFactory, question: str, source: str, words: str
) -> None:
    project, env = _built(tmp_path_factory)
    code, shown = _run(project, env, "query", question, "--render", "json")
    assert code == 0, shown[-3000:]
    answer = json.loads(shown[: shown.rindex("}") + 1])
    hits = [hit for hit in answer["evidence"] if hit["doc_uri"] == source]
    assert any(words in hit["text"] for hit in hits), answer["evidence"]


def test_a_question_is_answered_first_by_the_block_that_answers_it(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """D649: with the stopwords out of the terms, the notes block that says when the launch moves
    is the first evidence, and not the onboarding guide's sentence about *the* and *does*."""
    project, env = _built(tmp_path_factory)
    code, shown = _run(project, env, "query", "when does the launch move", "--render", "json")
    assert code == 0, shown[-3000:]
    first = json.loads(shown[: shown.rindex("}") + 1])["evidence"][0]
    assert (first["doc_uri"], first["text"][:30]) == ("notes.txt", "The launch moves to April 14 b")


_BUILT: dict[str, tuple[Path, dict[str, str]]] = {}


def _built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    """One project for the five questions, built once: `ow add` over the five fixtures."""
    if "project" in _BUILT:
        return _BUILT["project"]
    root = tmp_path_factory.mktemp("text-formats")
    project = root / "project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    for name in FILES:
        shutil.copyfile(FIXTURES / name, project / "docs" / name)
    home = root / "home"
    home.mkdir()
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    env = {**keep, "HOME": str(home), "USERPROFILE": str(home), "OMNIWEAVE_HOME": str(root / "ow")}
    code, shown = _run(project, env, "add", "docs")
    assert code == 0, shown[-3000:]
    assert "5 parsed (parse.text.builtin 5)" in shown, shown[-3000:]
    connection = sqlite3.connect(project / ".omniweave" / "docs.owstore")
    try:
        states = connection.execute("SELECT DISTINCT state FROM unit").fetchall()
        formats = sorted(row[0] for row in connection.execute("SELECT format FROM doc"))
    finally:
        connection.close()
    assert states == [("settled",)]
    assert formats == ["html", "ipynb", "json", "md", "txt"]
    _BUILT["project"] = (project, env)
    return _BUILT["project"]
