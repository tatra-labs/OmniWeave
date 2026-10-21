"""`OmniweaveLoader(BaseLoader)` and `OmniweaveBlobParser(BaseBlobParser)`. D909.

Files in, LangChain Documents out, with omniweave doing the parsing: each file is added to a corpus
(`Corpus.add`, as `ow add` does) and each of its documents comes back as one Document holding its
Markdown serialization (`_common` ruling 3).

## Rulings

1. **Adding is indexing.** The loader writes to the corpus it is given, so the documents it returns
   are also searchable through `OmniweaveRetriever` and citable by the tool. A file already
   indexed and unchanged is not parsed again; its document is still returned.
2. **A file's document is found by its `unit_uri`** (`Corpus.doc(canonical_uri(path))`), not read
   off the add's report, which lists only what that run parsed. A file the corpus refused (not a
   document, encrypted without a password) has no document and yields nothing; its refusal is the
   add's report and `ow doctor`'s, and a loader that raised on it would make one bad file in a
   folder fail the whole load.
3. **A blob is parsed by its path.** A Blob held only in memory has no place in a corpus, and a
   document's identity is its place (D905), so `lazy_parse` refuses it by name rather than invent
   a temporary path that would become its identity.
4. **Lossy, and said so** (`_index/interfaces.md:187-189`): a Document is text. Geometry, spans
   and restriction bits stay in the corpus; `OmniweaveRetriever`'s metadata carries the cite that
   reaches them, and the tool's artifact carries the whole `Answer`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.document_loaders import BaseBlobParser, BaseLoader
from langchain_core.documents import Document
from omniweave_core.errors import NotFoundError
from omniweave_core.identity import canonical_uri

from omniweave_langchain._common import FORMAT, document_metadata, open_corpus

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from langchain_core.document_loaders.blob_loaders import Blob
    from omniweave.sdk.api import Corpus

__all__ = ["OmniweaveBlobParser", "OmniweaveLoader"]


def _files(paths: Sequence[Path]) -> list[Path]:
    """Every file under `paths`, in path order: a directory's files, or the file itself."""
    out: list[Path] = []
    for path in paths:
        out.extend(sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path])
    return out


def _documents(corpus: Corpus, files: Sequence[Path]) -> Iterator[Document]:
    """Rulings 2 and 4: one Document per file that has a document, in path order."""
    for path in files:
        try:
            doc = corpus.doc(canonical_uri(path.resolve()))
        except NotFoundError:
            continue
        text, _spans = doc.serialize(FORMAT)
        yield Document(page_content=text, metadata=document_metadata(corpus, doc))


class OmniweaveLoader(BaseLoader):
    """Files or folders added to a corpus, each document returned as one LangChain Document."""

    def __init__(
        self,
        paths: str | Path | Sequence[str | Path],
        *,
        corpus: str | None = None,
        config: str | Path | None = None,
    ) -> None:
        sources = [paths] if isinstance(paths, (str, Path)) else list(paths)
        self.paths = [Path(source) for source in sources]
        self.corpus = corpus
        self.config = config

    def lazy_load(self) -> Iterator[Document]:
        """Ruling 1: add every path, then yield each file's document."""
        handle = open_corpus(self.corpus, self.config, readonly=False)
        handle.add([str(path) for path in self.paths])
        yield from _documents(handle, _files(self.paths))


class OmniweaveBlobParser(BaseBlobParser):
    """omniweave as the parser under any `BlobLoader` that yields file blobs."""

    def __init__(self, *, corpus: str | None = None, config: str | Path | None = None) -> None:
        self.corpus = corpus
        self.config = config

    def lazy_parse(self, blob: Blob) -> Iterator[Document]:
        """Ruling 3: the blob's file, added and returned as its document."""
        if blob.path is None:
            message = (
                "OmniweaveBlobParser parses a blob by its path, and this one is held in memory: "
                "a document's identity is its place in the corpus, so write it to a file first"
            )
            raise ValueError(message)
        path = Path(str(blob.path))
        handle = open_corpus(self.corpus, self.config, readonly=False)
        handle.add(str(path))
        yield from _documents(handle, [path])
