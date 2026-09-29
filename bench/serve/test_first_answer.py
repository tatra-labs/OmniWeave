"""`first_answer.py`'s rules: the folder, the judge, the verdict and the exit. V01-15 (00:716).

The run itself -- three real children over a real folder -- is
`packages/omniweave/tests/conform/test_first_answer_process.py`, because a test that spawns a
process belongs to the `conform` tier (13-quality.md section 2.7).
"""

from __future__ import annotations

import json
import os
import sqlite3  # noqa: TID251 -- the judge's store is built here, three tables of it.
import zipfile
from pathlib import Path

import first_answer as fa
import pytest

# ---------------------------------------------------------------------------------------------
# The folder
# ---------------------------------------------------------------------------------------------


def test_the_folder_is_a_function_of_this_file_and_n(tmp_path: Path) -> None:
    """Fixed ZIP dates and stored entries, as the fixture generator's: a rerun is byte-identical."""
    first = fa.office_folder(tmp_path / "a", 9)
    second = fa.office_folder(tmp_path / "b", 9)
    assert [p.read_bytes() for p in first.files] == [p.read_bytes() for p in second.files]
    assert (first.question, first.expected) == (second.question, second.expected)


def test_the_folder_is_a_third_each_docx_pptx_and_xlsx_and_every_file_is_a_zip(
    tmp_path: Path,
) -> None:
    folder = fa.office_folder(tmp_path, fa.DOCS)
    assert len(folder.files) == 100
    suffixes = [p.suffix for p in folder.files]
    assert (suffixes.count(".docx"), suffixes.count(".pptx"), suffixes.count(".xlsx")) == (
        34,
        33,
        33,
    )
    for path in folder.files:
        with zipfile.ZipFile(path) as archive:
            assert "[Content_Types].xml" in archive.namelist()


def test_the_needle_is_a_docx_whose_text_carries_the_expected_answer(tmp_path: Path) -> None:
    folder = fa.office_folder(tmp_path, fa.DOCS)
    assert folder.needle.name == "agreement-042.docx"
    assert folder.question == "What is the notice period under agreement 042?"
    with zipfile.ZipFile(folder.needle) as archive:
        body = archive.read("word/document.xml").decode("utf-8")
    assert f"The notice period under agreement 042 is {folder.expected}." in body
    #  No other document states the needle's number, so a right cite is a cite of the needle.
    others = [p for p in folder.files if p != folder.needle]
    for path in others:
        with zipfile.ZipFile(path) as archive:
            assert all(b"042" not in archive.read(name) for name in archive.namelist())


@pytest.mark.parametrize("n", [1, 2, 3, 7])
def test_a_small_folder_still_has_a_docx_needle(tmp_path: Path, n: int) -> None:
    folder = fa.office_folder(tmp_path, n)
    assert len(folder.files) == n
    assert folder.needle.suffix == ".docx"
    assert folder.needle in folder.files


def test_an_empty_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one document"):
        fa.office_folder(tmp_path, 0)


# ---------------------------------------------------------------------------------------------
# The judge
# ---------------------------------------------------------------------------------------------

NEEDLE = Path("C:/work/project/docs/agreement-042.docx")


def _store(tmp_path: Path, pages: dict[tuple[int, int], str]) -> Path:
    """The three tables `judge()` reads: `block`, `page` and `enum_val`, at the shipped ordinals."""
    path = tmp_path / "judge.owstore"
    connection = sqlite3.connect(path)
    kinds = {"page": 0, "slide": 1, "sheet": 2, "frame": 3, "stream": 4}
    connection.executescript(
        "CREATE TABLE enum_val (domain TEXT, ord INTEGER, name TEXT);"
        "CREATE TABLE page (doc_ord INTEGER, gen INTEGER, page INTEGER, page_kind INTEGER);"
        "CREATE TABLE block (doc_ord INTEGER, gen INTEGER, page INTEGER);"
    )
    connection.executemany(
        "INSERT INTO enum_val VALUES ('page_kind', ?, ?)", [(o, n) for n, o in kinds.items()]
    )
    for (doc_ord, page), kind in pages.items():
        connection.execute("INSERT INTO page VALUES (?, 1, ?, ?)", (doc_ord, page, kinds[kind]))
        connection.execute("INSERT INTO block VALUES (?, 1, ?)", (doc_ord, page))
    connection.commit()
    connection.close()
    return path


def _block(cite: str, doc_uri: str, page: int = 0, text: str = "") -> dict[str, object]:
    return {"cite": cite, "doc_uri": doc_uri, "page": page, "text": text}


def test_the_needle_is_named_by_its_relative_doc_uri() -> None:
    """The Answer's `doc_uri` is relative to the corpus source, as the first run showed."""
    assert fa._names(NEEDLE, "agreement-042.docx")
    assert fa._names(NEEDLE, "docs/agreement-042.docx")
    assert fa._names(NEEDLE, "docs\\Agreement-042.DOCX")
    assert fa._names(NEEDLE, NEEDLE.as_posix())
    assert not fa._names(NEEDLE, "greement-042.docx")
    assert not fa._names(NEEDLE, "")


def test_an_office_answer_cites_the_needle_and_carries_no_page(tmp_path: Path) -> None:
    store = _store(tmp_path, {(4, 0): "stream", (1, 0): "stream"})
    answer = {
        "evidence": [
            _block(
                "d4#5",
                "agreement-042.docx",
                text="The notice period under agreement 042 is 64 days.",
            ),
            _block(
                "d1#5",
                "agreement-000.docx",
                text="The notice period under agreement 000 is 10 days.",
            ),
        ]
    }
    judged = fa.judge(answer, store=store, needle=NEEDLE, expected="64 days")
    assert judged == fa.Judgement(
        cited=2,
        needle_cited=True,
        answered=True,
        paged=False,
        page_kinds=("stream",),
        needle_cite="d4#5",
    )
    #  ADR-13 D13.1: every cited page is `stream`, which has no page, so the clause holds.
    assert judged.page_clause


def test_a_cite_on_a_real_page_is_paged_and_a_wrong_document_is_not_the_needle(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, {(2, 3): "page"})
    answer = {"evidence": [_block("docs:d2#9", "contract.pdf", page=3, text="64 days")]}
    judged = fa.judge(answer, store=store, needle=NEEDLE, expected="64 days")
    assert (judged.paged, judged.needle_cited, judged.answered) == (True, False, False)
    assert judged.page_kinds == ("page",)


def test_a_block_with_no_page_row_is_unknown_never_paged(tmp_path: Path) -> None:
    store = _store(tmp_path, {})
    answer = {"evidence": [_block("d9#1", "agreement-042.docx")], "state": "found"}
    judged = fa.judge(answer, store=store, needle=NEEDLE, expected="64 days")
    assert (judged.paged, judged.page_kinds, judged.answered) == (False, ("unknown",), False)


def test_an_answer_with_no_evidence_cites_nothing(tmp_path: Path) -> None:
    judged = fa.judge({"state": "absent"}, store=_store(tmp_path, {}), needle=NEEDLE, expected="x")
    assert (judged.cited, judged.needle_cited) == (0, False)


# ---------------------------------------------------------------------------------------------
# The verdict and the exit
# ---------------------------------------------------------------------------------------------

CITED = fa.Judgement(cited=3, needle_cited=True, answered=True, paged=False, page_kinds=("stream",))


def _measured(**over: object) -> fa.Measurement:
    fields: dict[str, object] = {
        "first_answer_seconds": 24.0,
        "phases": {"install": 0.4, "add": 23.3, "query": 0.3},
        "docs": 100,
        "question": "q",
        "judgement": CITED,
        "machine": {"cpus": 4, "platform": "p", "python": "3.12", "clean": False},
        "reversed": True,
        "resolved": True,
    }
    fields.update(over)
    return fa.Measurement(**fields)  # type: ignore[arg-type]


def test_it_passes_within_the_budget_citing_the_needle_whether_or_not_on_a_page() -> None:
    """The page clause is reported, and it is not the exit: no office document has one (D615)."""
    assert _measured().passed
    assert _measured(first_answer_seconds=600.0).passed
    assert not _measured(first_answer_seconds=600.1).passed
    wrong = fa.Judgement(cited=3, needle_cited=False, answered=False, paged=True, page_kinds=())
    assert not _measured(judgement=wrong).passed
    assert not _measured(judgement=None).passed
    assert not _measured(failed="ow add: exit 1: boom").passed


@pytest.mark.parametrize(
    ("kinds", "paged", "holds"),
    [
        (("stream",), False, True),
        (("page",), True, True),
        (("page", "stream"), True, True),
        (("unknown",), False, False),
        (("stream", "unknown"), False, False),
        ((), False, False),
    ],
)
def test_the_page_clause_is_read_by_page_kind(
    kinds: tuple[str, ...], paged: bool, holds: bool
) -> None:
    """ADR-13 D13.1: a page wherever the page kind has one. A block with no page row is neither."""
    judged = fa.Judgement(cited=1, needle_cited=True, answered=True, paged=paged, page_kinds=kinds)
    assert judged.page_clause is holds


def test_a_cite_ow_open_does_not_resolve_or_a_failed_page_clause_fails_the_run() -> None:
    assert not _measured(resolved=False).passed
    assert not _measured(resolved=None).passed
    unknown = fa.Judgement(
        cited=1, needle_cited=True, answered=True, paged=False, page_kinds=("unknown",)
    )
    assert not _measured(judgement=unknown).passed


def test_an_uninstall_that_leaves_residue_fails_the_run() -> None:
    """16:736-737: the demo ends with a byte-identity diff of every path the install wrote."""
    assert not _measured(reversed=False, residue=(".claude.json",)).passed
    assert not _measured(reversed=None).passed


def test_the_snapshot_is_every_file_by_relative_path_and_digest(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.json").write_bytes(b"{}")
    (tmp_path / "top.md").write_bytes(b"x")
    (tmp_path / "empty").mkdir()
    snap = fa._snapshot(tmp_path)
    assert sorted(snap) == ["a/b/c.json", "top.md"]
    (tmp_path / "top.md").write_bytes(b"y")
    assert fa._snapshot(tmp_path)["top.md"] != snap["top.md"]


def test_the_uninstall_undoes_the_install_it_follows() -> None:
    for flag in ("--target", "--location"):
        assert fa.UNINSTALL[fa.UNINSTALL.index(flag) + 1] == fa.INSTALL[fa.INSTALL.index(flag) + 1]
    assert fa.UNINSTALL[0] == "uninstall"
    assert "--yes" in fa.UNINSTALL


def _returning(result: fa.Measurement) -> object:
    """`measure()`'s signature, answering `result` without running anything."""

    def measure(n: int, *, work: Path) -> fa.Measurement:
        assert n > 0
        assert work.is_dir()
        return result

    return measure


@pytest.mark.parametrize(
    ("result", "exit_code"),
    [
        (_measured(), 0),
        (_measured(first_answer_seconds=900.0), 1),
        (_measured(judgement=None, failed="ow install: exit 1: no"), 2),
    ],
)
def test_the_exit_is_0_pass_1_fail_2_a_verb_failed(
    result: fa.Measurement,
    exit_code: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(fa, "measure", _returning(result))
    assert fa.main(["--docs", "3", "--json"]) == exit_code
    document = json.loads(capsys.readouterr().out)
    assert document["passed"] is (exit_code == 0)
    assert document["machine"]["clean"] is False


def test_the_text_report_names_the_machine_and_never_calls_it_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(fa, "measure", _returning(_measured(notes=("n1",))))
    assert fa.main([]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("first_answer_seconds 24.0 s against 600 s")
    assert out[2].endswith("on a page False (page kinds: stream); ow open resolves True")
    assert out[3] == "reverse ow uninstall: the home is byte-identical"
    assert out[4].endswith("not a clean machine")
    assert out[-2:] == ["note    n1", "PASS"]


def test_the_verbs_run_under_a_home_of_their_own(tmp_path: Path) -> None:
    """Nothing of the user's is read or written: `HOME`, `USERPROFILE` and `OMNIWEAVE_HOME`."""
    env = fa._env(tmp_path)
    assert env["HOME"] == env["USERPROFILE"] == str(tmp_path / "home")
    assert env["OMNIWEAVE_HOME"] == str(tmp_path / "owhome")
    assert "PYTHONIOENCODING" not in env


def test_the_install_is_one_unattended_global_claude_code_install() -> None:
    assert fa.INSTALL[:1] == ("install",)
    assert "--yes" in fa.INSTALL
    assert fa.INSTALL[fa.INSTALL.index("--target") + 1] == "claude-code"


def test_the_machine_is_recorded_as_it_is_and_never_as_clean() -> None:
    """00:716's machine is a clean 4-core one with no GPU; this run's is whatever started it."""
    machine = fa._machine()
    assert machine["clean"] is False
    assert machine["cpus"] == os.cpu_count()
    assert set(machine) == {"cpus", "platform", "python", "clean"}
