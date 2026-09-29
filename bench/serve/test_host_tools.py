"""The emulated host tools: Read, Grep and a read-only Bash, confined to the corpus (ADR-14)."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pytest
import serve_harness as h
from host_tools import READ_WINDOW, HostTools
from models import ToolUse

REPO = Path(__file__).resolve().parents[2]
PDF = REPO / "packages" / "omniweave-pdf" / "fixtures"
OFFICE = REPO / "packages" / "omniweave-office" / "fixtures"


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    (root / "sub").mkdir(parents=True)
    (root / "notice.txt").write_text(
        "\n".join(f"line {n}" for n in range(1, 2_501)) + "\nNotice is thirty days.\n",
        encoding="utf-8",
    )
    (root / "sub" / "memo.md").write_text("# Memo\nZanzibar arbitration.\n", encoding="utf-8")
    shutil.copy(PDF / "gen02p.pdf", root / "contract.pdf")
    shutil.copy(PDF / "no_text_layer.pdf", root / "scan.pdf")
    shutil.copy(OFFICE / "rich.docx", root / "report.docx")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    return root


def _call(tools: HostTools, name: str, **arguments: object):
    return tools.call(ToolUse("u1", name, arguments))


def test_read_is_numbered_windowed_and_says_how_to_read_on(docs: Path) -> None:
    tools = HostTools(docs)
    first = _call(tools, "Read", file_path="notice.txt")
    lines = first.result.text.splitlines()
    assert lines[0] == "     1\tline 1"
    assert len([line for line in lines if "\t" in line]) == READ_WINDOW
    assert "read on with offset=2001" in first.result.text
    tail = _call(tools, "Read", file_path="notice.txt", offset=2501, limit=5)
    assert tail.result.text.splitlines() == ["  2501\tNotice is thirty days."]
    assert first.call == h.ToolCall("Read", {"file_path": (docs / "notice.txt").as_posix()})


@pytest.mark.parametrize("path", ["../outside.txt", "sub/../../outside.txt"])
def test_read_outside_the_folder_is_refused_as_an_error_the_model_reads(
    docs: Path, path: str
) -> None:
    done = _call(HostTools(docs), "Read", file_path=path)
    assert done.result.is_error
    assert "outside the documents folder" in done.result.text
    assert "secret" not in done.result.text


def test_a_pdf_is_its_text_layer_per_page(docs: Path) -> None:
    done = _call(HostTools(docs), "Read", file_path="contract.pdf")
    assert "--- page 1 ---" in done.result.text
    assert "Schedule and severance" in done.result.text
    assert done.result.images == ()


def test_a_pdf_page_with_no_text_layer_comes_back_as_its_image(docs: Path) -> None:
    done = _call(HostTools(docs), "Read", file_path="scan.pdf")
    assert "no text layer; returned as an image" in done.result.text
    (image,) = done.result.images
    assert image.media_type == "image/png"
    assert base64.b64decode(image.data_b64).startswith(b"\x89PNG\r\n\x1a\n")


def test_an_office_document_is_anydoc_markdown(docs: Path) -> None:
    done = _call(HostTools(docs), "Read", file_path="report.docx")
    assert "# Quarterly report" in done.result.text
    assert "| Q1 | 120 |" in done.result.text


def test_grep_lists_files_or_lines_over_the_converted_text(docs: Path) -> None:
    tools = HostTools(docs)
    listed = _call(tools, "Grep", pattern="zanzibar", case_insensitive=True)
    assert listed.result.text == (docs / "sub" / "memo.md").as_posix()
    lines = _call(tools, "Grep", pattern="Schedule", path=".", output_mode="content")
    assert lines.result.text.startswith((docs / "contract.pdf").as_posix() + ":")
    none = _call(tools, "Grep", pattern="Schedule", glob="*.md")
    assert none.result.text == "No matches found"
    assert listed.call.args["path"] == docs.as_posix()


def test_bash_runs_readers_and_records_their_paths_absolute(docs: Path) -> None:
    tools = HostTools(docs)
    done = _call(tools, "Bash", command="head -n 1 notice.txt")
    assert done.result.text == "line 1"
    assert done.call.args["command"] == f"head -n 1 {(docs / 'notice.txt').as_posix()}"
    assert "memo.md" in _call(tools, "Bash", command="ls -R").result.text
    assert _call(tools, "Bash", command="find . -name '*.pdf'").result.text.count(".pdf") == 2
    assert "Zanzibar" in _call(tools, "Bash", command="grep -i zanzibar sub").result.text


@pytest.mark.parametrize(
    ("command", "says"),
    [
        ("cat notice.txt | head", "pipes"),
        ("rm notice.txt", "not available"),
        ("python -c 1", "not available"),
        ("cat $(ls)", "pipes"),
        ("cat ../outside.txt", "outside"),
    ],
)
def test_bash_refuses_anything_but_one_read_only_command(
    docs: Path, command: str, says: str
) -> None:
    done = _call(HostTools(docs), "Bash", command=command)
    assert says in done.result.text
    assert "secret" not in done.result.text


def test_what_the_tools_record_is_what_the_harness_counts_as_a_reread(docs: Path) -> None:
    tools = HostTools(docs)
    indexed = h.indexed_sources("notice.txt\nsub/memo.md\n", docs.as_posix())
    reads = [
        _call(tools, "Read", file_path="notice.txt").call,
        _call(tools, "Grep", pattern="x", path="sub").call,
        _call(tools, "Bash", command="cat notice.txt").call,
    ]
    assert [h.reads_source(call, indexed) for call in reads] == [True, True, True]
    listing = _call(tools, "Bash", command="ls").call
    assert h.reads_source(listing, indexed) is False
