"""The adapter over a real corpus: loaded, retrieved and asked, every cite resolving. D909.

`OmniweaveLoader.load()` is `Corpus.add`, which spawns parse workers, so the conform tier (Q-G25).
The three surfaces share one project, as an agent would: the loader indexes, and the retriever
and the tool read what it indexed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage
from omniweave_langchain import (
    OmniweaveBlobParser,
    OmniweaveLoader,
    OmniweaveRetriever,
    create_omniweave_tool,
)

import omniweave

pytestmark = pytest.mark.conform

PROJECT = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
CAP = b"The indemnity cap is two million euros.\n\nEach party bears its own costs.\n"
NOTICE = b"Notice must be given thirty days in advance.\n"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "omniweave.toml").write_bytes(PROJECT.encode())
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "cap.txt").write_bytes(CAP)
    (tmp_path / "docs" / "notice.txt").write_bytes(NOTICE)
    monkeypatch.setenv("OMNIWEAVE_HOME", str(tmp_path / "owhome"))
    return tmp_path


def test_loaded_documents_are_retrievable_and_citable(project: Path) -> None:
    config = project / "omniweave.toml"
    loaded = OmniweaveLoader(project / "docs", config=config).load()
    assert [d.metadata["ow_doc_uri"].rsplit("/", 1)[-1] for d in loaded] == [
        "cap.txt",
        "notice.txt",
    ]
    assert "indemnity cap is two million euros" in loaded[0].page_content

    found = OmniweaveRetriever(config=config).invoke("indemnity cap")
    assert found, "the passage the loader indexed is retrieved"
    assert "two million euros" in found[0].page_content
    corpus = omniweave.corpus(None, config=config, cwd=project)
    cited = corpus.doc(found[0].metadata["cite"])
    assert f"d{cited.doc_ord}" == loaded[0].metadata["ow_doc"], "the cite resolves to cap.txt"

    ask = create_omniweave_tool(config=config)
    message = ask.invoke(
        {"type": "tool_call", "id": "c1", "name": ask.name, "args": {"question": "notice period"}}
    )
    assert isinstance(message, ToolMessage)
    assert "thirty days" in str(message.content)
    assert message.artifact.evidence, "the artifact is the Answer the content was rendered from"
    for block in message.artifact.evidence:
        assert block.cite in str(message.content)


def test_a_second_load_returns_the_same_documents_without_new_ones(project: Path) -> None:
    """Loader ruling 1: an unchanged file is not parsed again, and its document still returns."""
    config = project / "omniweave.toml"
    first = OmniweaveLoader(project / "docs", config=config).load()
    again = OmniweaveLoader(project / "docs", config=config).load()
    assert [d.metadata["ow_doc"] for d in again] == [d.metadata["ow_doc"] for d in first]
    assert [d.metadata["ow_gen"] for d in again] == [d.metadata["ow_gen"] for d in first]


def test_the_blob_parser_adds_one_file(project: Path) -> None:
    from langchain_core.document_loaders.blob_loaders import Blob  # noqa: PLC0415

    config = project / "omniweave.toml"
    parsed = OmniweaveBlobParser(config=config).parse(Blob.from_path(project / "docs" / "cap.txt"))
    assert len(parsed) == 1
    assert parsed[0].metadata["ow_doc_uri"].endswith("/cap.txt")
