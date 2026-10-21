"""The LangChain adapter's loader, retriever and tool, over a stand-in corpus. D909.

Each surface opens its corpus through `_common.open_corpus`, so a stand-in there is the whole
seam: what is asked of the corpus (an add, a doc by `unit_uri`, a query with `k` and `max_chars`)
and what comes back as LangChain types. A real `ow add` spawns parse workers, so the end-to-end
run is `tests/conform/test_langchain_end_to_end.py`'s.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import omniweave_langchain
import pytest
from langchain_core.document_loaders.blob_loaders import Blob
from langchain_core.messages import ToolMessage
from omniweave_core.answer.render import Answer, RenderedBlock, render
from omniweave_core.errors import NotFoundError
from omniweave_core.identity import canonical_uri
from omniweave_core.model.enums import Quote
from omniweave_langchain import (
    OmniweaveBlobParser,
    OmniweaveLoader,
    OmniweaveRetriever,
    _common,
    create_omniweave_tool,
    loader,
    retriever,
    tool,
)

DIST_ROOT = Path(__file__).resolve().parents[2]
REPO = DIST_ROOT.parents[1]


def _block(ordinal: int, **over: object) -> RenderedBlock:
    fields: dict[str, object] = {
        "cite": f"docs:d3#{ordinal}",
        "addr": f"p1/{ordinal}",
        "doc_uri": "contracts/cap.txt",
        "page": 1,
        "kind": "paragraph",
        "text": f"The indemnity cap is {ordinal} million euros.",
        "quote": Quote.VERBATIM,
        "trust": "extracted",
        "method": "text_layer",
        "origin_driver": "parse.text.plain@1",
        "byte_exact": True,
    }
    fields.update(over)
    return RenderedBlock(**fields)  # type: ignore[arg-type]


def _answer(*blocks: RenderedBlock) -> Answer:
    return Answer(state="ok", corpus="docs", generation=4, freshness="fresh", evidence=blocks)


def _doc(uri: str, doc_ord: int, text: str) -> SimpleNamespace:
    record = SimpleNamespace(uri=uri, media_type="text/plain", format="txt", page_count=None)

    def serialize(fmt: str) -> tuple[str, tuple[()]]:
        assert fmt == "md", "_common ruling 3: a Document holds the Markdown serialization"
        return text, ()

    return SimpleNamespace(rec=record, doc_ord=doc_ord, gen=2, serialize=serialize)


@dataclass
class _Corpus:
    """What the adapter asks of `omniweave.sdk.api.Corpus`, and a record of every ask."""

    docs: dict[str, SimpleNamespace] = field(default_factory=dict)
    answer: Answer = field(default_factory=lambda: _answer(_block(1), _block(2)))
    name: str = "docs"
    added: list[object] = field(default_factory=list)
    queries: list[tuple[str, int, int]] = field(default_factory=list)

    def add(self, paths: object) -> None:
        self.added.append(paths)

    def doc(self, ref: str) -> SimpleNamespace:
        if ref not in self.docs:
            raise NotFoundError(f"no document {ref}", fix="ow add <path>")
        return self.docs[ref]

    def query(self, text: str, *, k: int, max_chars: int) -> Answer:
        self.queries.append((text, k, max_chars))
        return self.answer


@pytest.fixture
def opened() -> list[tuple[str | None, object, bool]]:
    """Every `open_corpus(name, config, readonly=)` the surfaces make, in order."""
    return []


def _stand_in(
    monkeypatch: pytest.MonkeyPatch,
    corpus: _Corpus,
    opened: list[tuple[str | None, object, bool]],
) -> None:
    def open_corpus(name: str | None, config: object, *, readonly: bool) -> _Corpus:
        opened.append((name, config, readonly))
        return corpus

    for module in (loader, retriever, tool):
        monkeypatch.setattr(module, "open_corpus", open_corpus)


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    folder = tmp_path / "docs"
    folder.mkdir()
    cap, notice, refused = folder / "cap.txt", folder / "notice.txt", folder / "z.bin"
    for path in (cap, notice, refused):
        path.write_bytes(b"x\n")
    return cap, notice, refused


# ---------------------------------------------------------------------------------------------
# The distribution
# ---------------------------------------------------------------------------------------------


def test_the_distribution_declares_itself_an_attachment_on_its_own_series() -> None:
    """11-repo-layout.md section 1.2's second table: outside the fourteen, its version its own."""
    data = tomllib.loads((DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["tool"]["omniweave"] == {"attachment": True}
    assert data["project"]["name"] == "omniweave-langchain"
    assert data["project"]["dependencies"] == ["omniweave ~= 0.1.0", "langchain-core >=1.0,<2"]


def test_its_layer_row_is_the_sdk_by_the_d909_ruling_closed_over_the_sdks_row() -> None:
    layers = tomllib.loads((REPO / "tools" / "layers.toml").read_text(encoding="utf-8"))
    row = layers["omniweave_langchain"]
    assert "omniweave" in row
    assert set(layers["omniweave"]) <= set(row)


def test_the_package_exports_the_four_surfaces() -> None:
    assert omniweave_langchain.__all__ == [
        "OmniweaveBlobParser",
        "OmniweaveLoader",
        "OmniweaveRetriever",
        "create_omniweave_tool",
    ]


# ---------------------------------------------------------------------------------------------
# open_corpus
# ---------------------------------------------------------------------------------------------


def test_an_explicit_config_resolves_store_paths_from_its_own_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`_common` ruling 1: as `ow --config` run from the project's directory would."""
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        "omniweave.corpus", lambda name, **kw: seen.append({"name": name, **kw}) or "handle"
    )
    config = tmp_path / "proj" / "omniweave.toml"
    assert _common.open_corpus("docs", config, readonly=True) == "handle"
    assert _common.open_corpus(None, None, readonly=False) == "handle"
    assert seen == [
        {"name": "docs", "config": config, "readonly": True, "cwd": config.resolve().parent},
        {"name": None, "config": None, "readonly": False, "cwd": None},
    ]


# ---------------------------------------------------------------------------------------------
# The loader and the blob parser
# ---------------------------------------------------------------------------------------------


def test_the_loader_adds_then_returns_one_document_per_indexed_file_in_path_order(
    monkeypatch: pytest.MonkeyPatch,
    opened: list[tuple[str | None, object, bool]],
    tmp_path: Path,
) -> None:
    """Loader rulings 1, 2 and 4; the refused file has no document and yields nothing."""
    cap, notice, _refused = _files(tmp_path)
    corpus = _Corpus(
        docs={
            canonical_uri(notice.resolve()): _doc("docs/notice.txt", 4, "Notice: thirty days."),
            canonical_uri(cap.resolve()): _doc("docs/cap.txt", 3, "The cap is two million."),
        }
    )
    _stand_in(monkeypatch, corpus, opened)
    documents = OmniweaveLoader(tmp_path / "docs", corpus="docs", config="ow.toml").load()
    assert opened == [("docs", "ow.toml", False)]
    assert corpus.added == [[str(tmp_path / "docs")]]
    assert [d.page_content for d in documents] == [
        "The cap is two million.",
        "Notice: thirty days.",
    ]
    assert documents[0].metadata == {
        "ow_corpus": "docs",
        "ow_doc": "d3",
        "ow_doc_uri": "docs/cap.txt",
        "ow_media_type": "text/plain",
        "ow_format": "txt",
        "ow_gen": 2,
        "ow_pages": 0,
        "source": "docs/cap.txt",
    }


def test_the_loader_takes_one_path_or_many(
    monkeypatch: pytest.MonkeyPatch,
    opened: list[tuple[str | None, object, bool]],
    tmp_path: Path,
) -> None:
    cap, notice, _refused = _files(tmp_path)
    corpus = _Corpus(docs={canonical_uri(cap.resolve()): _doc("docs/cap.txt", 3, "cap")})
    _stand_in(monkeypatch, corpus, opened)
    assert [d.page_content for d in OmniweaveLoader(str(cap)).lazy_load()] == ["cap"]
    assert list(OmniweaveLoader([notice]).lazy_load()) == []
    assert corpus.added == [[str(cap)], [str(notice)]]


def test_a_blob_with_a_path_is_added_and_returned_as_its_document(
    monkeypatch: pytest.MonkeyPatch,
    opened: list[tuple[str | None, object, bool]],
    tmp_path: Path,
) -> None:
    cap, _notice, _refused = _files(tmp_path)
    corpus = _Corpus(docs={canonical_uri(cap.resolve()): _doc("docs/cap.txt", 3, "cap")})
    _stand_in(monkeypatch, corpus, opened)
    parsed = OmniweaveBlobParser(corpus="docs").parse(Blob.from_path(cap))
    assert [d.metadata["ow_doc"] for d in parsed] == ["d3"]
    assert corpus.added == [str(cap)]
    assert opened == [("docs", None, False)]


def test_a_blob_held_in_memory_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, opened: list[tuple[str | None, object, bool]]
) -> None:
    """Loader ruling 3: no temporary path is invented to become the document's identity."""
    corpus = _Corpus()
    _stand_in(monkeypatch, corpus, opened)
    with pytest.raises(ValueError, match="held in memory") as caught:
        OmniweaveBlobParser().parse(Blob.from_data(b"The cap is two million."))
    assert "write it to a file first" in str(caught.value)
    assert (opened, corpus.added) == ([], [])


# ---------------------------------------------------------------------------------------------
# The retriever
# ---------------------------------------------------------------------------------------------


def test_the_retriever_is_one_read_only_query_and_one_document_per_evidence_block(
    monkeypatch: pytest.MonkeyPatch, opened: list[tuple[str | None, object, bool]]
) -> None:
    """Retriever rulings 1-3, and `_common` ruling 2's metadata: the cite, never the score."""
    corpus = _Corpus(answer=_answer(_block(1), _block(2, quote=Quote.REFLOWED, byte_exact=False)))
    _stand_in(monkeypatch, corpus, opened)
    found = OmniweaveRetriever(corpus="docs", k=7, max_chars=9000).invoke("indemnity cap")
    assert opened == [("docs", None, True)]
    assert corpus.queries == [("indemnity cap", 7, 9000)]
    assert [d.page_content for d in found] == [
        "The indemnity cap is 1 million euros.",
        "The indemnity cap is 2 million euros.",
    ]
    assert found[1].metadata == {
        "cite": "docs:d3#2",
        "ow_corpus": "docs",
        "ow_doc_uri": "contracts/cap.txt",
        "ow_page": 1,
        "ow_kind": "paragraph",
        "ow_quote": "reflowed",
        "ow_trust": "extracted",
        "ow_method": "text_layer",
        "ow_origin_driver": "parse.text.plain@1",
        "ow_byte_exact": False,
        "ow_restriction": "\N{EN DASH}",
        "source": "contracts/cap.txt",
    }


def test_retriever_metadata_is_flat_and_scalar() -> None:
    """`_common` ruling 2: LangChain hashes metadata into a Document's identity."""
    metadata = _common.block_metadata("docs", _block(1))
    assert all(isinstance(value, (str, int, bool)) for value in metadata.values())
    assert {key for key in metadata if not key.startswith("ow_")} == {"cite", "source"}


def test_an_absent_answer_is_no_documents(
    monkeypatch: pytest.MonkeyPatch, opened: list[tuple[str | None, object, bool]]
) -> None:
    corpus = _Corpus(answer=_answer())
    _stand_in(monkeypatch, corpus, opened)
    assert OmniweaveRetriever().invoke("the moon") == []


# ---------------------------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------------------------


def test_the_tool_answers_with_the_rendered_text_and_the_answer_as_its_artifact(
    monkeypatch: pytest.MonkeyPatch, opened: list[tuple[str | None, object, bool]]
) -> None:
    """Tool rulings 1 and 2: `ToolMessage.content` is what `ow query` prints."""
    corpus = _Corpus()
    _stand_in(monkeypatch, corpus, opened)
    ask = create_omniweave_tool("docs", config="ow.toml", k=5, max_chars=8000)
    call = {"type": "tool_call", "id": "c1", "name": ask.name, "args": {"question": "cap"}}
    message = ask.invoke(call)
    assert isinstance(message, ToolMessage)
    assert message.artifact is corpus.answer
    assert message.content == render(corpus.answer, max_chars=8000)
    assert "docs:d3#1" in message.content
    assert opened == [("docs", "ow.toml", True)]
    assert corpus.queries == [("cap", 5, 8000)]


def test_the_tool_takes_one_argument_and_names_itself() -> None:
    """Tool ruling 3: one corpus, one question; a fan-out is deferred past v1.0 (D904)."""
    ask = create_omniweave_tool(name="handbook", description="Ask the handbook.")
    assert (ask.name, ask.description) == ("handbook", "Ask the handbook.")
    assert list(ask.args) == ["question"]
    assert ask.response_format == "content_and_artifact"
    assert create_omniweave_tool().description == tool.DESCRIPTION
