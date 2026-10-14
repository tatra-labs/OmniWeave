"""Embedded citations: the provenance part `read_back` recovers a `.docx`'s cites from.

09 section 10's embedded channel for OOXML is `customXml/omniweave-provenance.json`, the card's
`provenance_part`. It holds one row for each cited element and cite, in document order. A row
gives the element's `data-ow-el`, the canonical cite, the `doc_gen` the compile pinned it at
(`Plan.cites`), and its kind and span where the IL states them, with the corpus once for the
part. D786: it also maps every `data-ow-el` in the artefact to its construct (`els`). A
bookmark's two ends sit in the first and last paragraphs its element made, so the bookmark
alone cannot say whether `u01/e1` is a section or the heading it opens with. The construct can,
through `kind_map.toml`, and `parse.docx.native` reads it here. The part is written whether or
not anything is cited, so a reader can tell an artefact with no cites from one that is not
omniweave's. Visible text is never a citation.

D802: the rows, the two grammars and the body are the framework's,
`omniweave_core.out.provenance`, which a deck writes too. This module puts the body in the
document's package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from docx.opc.packuri import PackURI
from docx.opc.part import Part
from omniweave_core.canonical import JsonValue
from omniweave_core.out.provenance import MEDIA_TYPE, RELATIONSHIP, SCHEMA, body, kind, span

if TYPE_CHECKING:
    from docx.document import Document

__all__ = ["MEDIA_TYPE", "RELATIONSHIP", "SCHEMA", "kind", "provenance_part", "span"]


def provenance_part(
    document: Document,
    rows: Sequence[Mapping[str, JsonValue]],
    *,
    addresses: Mapping[str, str],
    name: str,
    corpus: str,
    slug: str,
    artifact_gen: int,
) -> None:
    """The part, canonical JSON, related from the package root."""
    package = document.part.package
    if package is None:  # pragma: no cover -- a loaded document always has one
        return
    data = body(rows, addresses, corpus=corpus, slug=slug, artifact_gen=artifact_gen)
    part = Part(PackURI(f"/{name}"), MEDIA_TYPE, data, package)
    package.relate_to(part, RELATIONSHIP)
