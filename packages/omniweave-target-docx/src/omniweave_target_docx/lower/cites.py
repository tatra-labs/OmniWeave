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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from docx.opc.packuri import PackURI
from docx.opc.part import Part
from omniweave_core.canonical import JsonValue, canonical
from omniweave_core.store.artifact import CITE_KINDS

if TYPE_CHECKING:
    from docx.document import Document

__all__ = ["MEDIA_TYPE", "RELATIONSHIP", "SCHEMA", "kind", "provenance_part", "span"]

SCHEMA: Final = "omniweave.out-provenance/1"
MEDIA_TYPE: Final = "application/json"
RELATIONSHIP: Final = "urn:omniweave:relationship:provenance"
"""A package relationship's type is a URI; this one names no place, so nothing can fetch it."""


def kind(value: str) -> str:
    """`data-ow-cite-kind`: one of the four kinds `artifact_cite` stores."""
    if value not in CITE_KINDS:
        msg = f"data-ow-cite-kind {value!r} is not one of {sorted(CITE_KINDS)}"
        raise ValueError(msg)
    return value


def span(value: str) -> tuple[int, int]:
    """`data-ow-cite-span="a:b"`: a range of the cited block's text, `a < b`."""
    a, sep, b = value.partition(":")
    if not sep or not a.isdecimal() or not b.isdecimal() or int(a) >= int(b):
        msg = f"data-ow-cite-span {value!r} is not a:b with a < b"
        raise ValueError(msg)
    return int(a), int(b)


def provenance_part(
    document: Document,
    rows: Sequence[dict[str, JsonValue]],
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
    body: JsonValue = {
        "schema": SCHEMA,
        "corpus": corpus,
        "slug": slug,
        "artifact_gen": artifact_gen,
        "cites": list(rows),
        "els": dict(sorted(addresses.items())),
    }
    part = Part(PackURI(f"/{name}"), MEDIA_TYPE, canonical(body), package)
    package.relate_to(part, RELATIONSHIP)
