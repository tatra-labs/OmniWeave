"""`OmniweaveRetriever(BaseRetriever)`: a corpus query as LangChain Documents. D909.

## Rulings

1. **One query is `Corpus.query()`**, exactly as `ow query` runs it: retrieve, fuse, gate and pack.
   The retriever adds no ranking of its own, so what it returns is what the CLI would cite.
2. **One Document per evidence block**, its text the passage and its metadata the cite and how it
   was read (`_common` ruling 2). The Answer's verdict -- `absent`, `degraded`, its gates -- has no
   place on a list of Documents; an agent that needs it uses `create_omniweave_tool`, whose
   artifact is the whole `Answer`.
3. **Read-only.** The corpus is opened `readonly=True`; the retriever never indexes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from omniweave_langchain._common import block_metadata, open_corpus

if TYPE_CHECKING:
    from langchain_core.callbacks import CallbackManagerForRetrieverRun

__all__ = ["OmniweaveRetriever"]


class OmniweaveRetriever(BaseRetriever):
    """Rulings 1-3: `corpus.query(query)`, each cited passage one Document."""

    corpus: str | None = None
    """The corpus name; `None` is `[serve] default_corpus`."""
    config: str | Path | None = None
    """An explicit `omniweave.toml`; `None` resolves from the working directory up."""
    k: int = 20
    max_chars: int = 24_000

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        del run_manager
        handle = open_corpus(self.corpus, self.config, readonly=True)
        answer = handle.query(query, k=self.k, max_chars=self.max_chars)
        return [
            Document(page_content=str(block.text), metadata=block_metadata(handle.name, block))
            for block in answer.evidence
        ]
