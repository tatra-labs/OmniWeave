"""What the loader, the retriever and the tool share: opening a corpus and shaping metadata. D909.

## Rulings

1. **A corpus is `omniweave.corpus()`**, by name or `[serve] default_corpus`, under the project's
   own configuration: an adapter that resolved stores itself would be a second resolver. A user
   ruling of 2026-10-21 lets this attachment import the SDK; 11-repo-layout.md section 1.2 printed
   core and ports only.
2. **Metadata is flat and scalar, every key `ow_`-prefixed but `cite`.** LangChain hashes
   `metadata` into a Document's identity for `index()` (`_index/in-04-agentic.md:43`), so a key
   whose value moves on every read (a score, a timestamp, geometry) would re-embed an unchanged
   passage. Only what names the passage and how it was read is carried; the full `Answer` rides
   the tool's artifact instead.
3. **A document is its Markdown serialization** (`Doc.serialize("md")`), one LangChain Document
   per omniweave document. Per-segment Documents wait for a segment reader (D866); by the same
   ruling the change is additive, a new loader mode, not a new meaning for this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave.sdk.api import Corpus
    from omniweave_core.answer.render import RenderedBlock
    from omniweave_core.model.doc import Doc

__all__ = ["FORMAT", "block_metadata", "document_metadata", "open_corpus"]

FORMAT: Final = "md"
"""Ruling 3: the serialization a LangChain Document's `page_content` holds."""


def open_corpus(name: str | None, config: str | Path | None, *, readonly: bool) -> Corpus:
    """Ruling 1: the SDK's handle, under the project's configuration.

    An explicit `config` is the project, so its directory is the one relative store paths resolve
    against, as `ow --config` would from that directory; without one, the working directory's.
    """
    from pathlib import Path  # noqa: PLC0415

    import omniweave  # noqa: PLC0415 -- use-time, so importing the adapter costs nothing

    cwd = None if config is None else Path(config).resolve().parent
    return omniweave.corpus(name, config=config, readonly=readonly, cwd=cwd)


def document_metadata(corpus: Corpus, doc: Doc) -> dict[str, str | int]:
    """Ruling 2 for a whole document: where it is, what it is, and which generation was read."""
    record = doc.rec
    return {
        "ow_corpus": corpus.name,
        "ow_doc": f"d{doc.doc_ord}",
        "ow_doc_uri": str(record.uri),
        "ow_media_type": str(record.media_type),
        "ow_format": str(record.format),
        "ow_gen": int(doc.gen),
        "ow_pages": int(record.page_count or 0),
        "source": str(record.uri),
    }


def block_metadata(corpus: str, block: RenderedBlock) -> dict[str, str | int | bool]:
    """Ruling 2 for one cited passage: its cite and how it was read, never its score.

    `ow_quote` is the wire value, the lower-case member name (`"verbatim"`): `Quote` is an
    `IntEnum`, so `str()` of it is its rung number, which reads as a count.
    """
    return {
        "cite": str(block.cite),
        "ow_corpus": corpus,
        "ow_doc_uri": str(block.doc_uri),
        "ow_page": int(block.page),
        "ow_kind": str(block.kind),
        "ow_quote": block.quote.name.lower(),
        "ow_trust": str(block.trust),
        "ow_method": str(block.method),
        "ow_origin_driver": str(block.origin_driver),
        "ow_byte_exact": bool(block.byte_exact),
        "ow_restriction": str(block.restriction),
        "source": str(block.doc_uri),
    }
