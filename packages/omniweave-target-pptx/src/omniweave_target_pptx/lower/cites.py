"""`lower.cites`: a deck's embedded citations, the provenance part `read_back` recovers. D802.

09 section 10's embedded channel for OOXML is the card's `provenance_part`,
`customXml/omniweave-provenance.json`, as a document's is. Its rows, the grammars of
`data-ow-cite-kind` and `data-ow-cite-span`, its address map and its body are the framework's
(`omniweave_core.out.provenance`), which docx writes too. This module puts the body in the
deck's package, related from its root, and writes it whether or not anything is cited. A cite
never draws: visible text is never a citation. D803: the part also lists where each address
landed (`at`), since a deck's runs have no name of their own to carry one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from omniweave_core.out.provenance import MEDIA_TYPE, RELATIONSHIP, body, kind, span
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI

if TYPE_CHECKING:
    from omniweave_core.canonical import JsonValue

__all__ = ["kind", "provenance_part", "span"]


def provenance_part(
    deck: object,
    rows: Sequence[Mapping[str, JsonValue]],
    *,
    addresses: Mapping[str, str],
    name: str,
    corpus: str,
    slug: str,
    artifact_gen: int,
    at: Mapping[str, Mapping[str, JsonValue]],
) -> None:
    """The part, canonical JSON, related from the package root."""
    package = deck.part.package  # type: ignore[attr-defined] -- a python-pptx Presentation
    data = body(rows, addresses, corpus=corpus, slug=slug, artifact_gen=artifact_gen, at=at)
    package.relate_to(Part(PackURI(f"/{name}"), MEDIA_TYPE, package, data), RELATIONSHIP)
