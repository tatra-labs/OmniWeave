"""Pictures: a frozen asset's bytes, inline, no wider than the text, with their alternative text.

A flow carrier has no geometry, so a picture's size is the compiler's: its own size at its own
resolution, scaled down in proportion when that is wider than the page's text column. Every length
is an EMU integer (09 section 6), so no float reaches the XML.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from docx.image.image import Image
from docx.shared import Emu

if TYPE_CHECKING:
    from docx.text.run import Run
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_docx.lower._emit import Emitter

__all__ = ["alt_text", "caption", "figure", "picture"]


def picture(em: Emitter, node: CarrierNode) -> None:
    """`img[src]`: the slot's bytes, which preflight 2 read from the ledger."""
    blob = em.assets[node.attr("src") or ""]
    image = Image.from_blob(blob)
    width, height = int(image.width), int(image.height)
    if width > em.text_width:
        width, height = em.text_width, height * em.text_width // width
    run = em.run()
    run.add_picture(io.BytesIO(blob), width=Emu(width), height=Emu(max(height, 1)))
    alt = node.attr("alt")
    if alt:
        alt_text(run, alt)
    em.at_start, em.pending = False, ""


def alt_text(run: Run, text: str) -> None:
    """`alt`: the drawing's `descr`, which a screen reader announces."""
    for properties in run._r.xpath(".//wp:docPr"):
        properties.set("descr", text)


def figure(em: Emitter, node: CarrierNode) -> None:
    em.flow(node)


def caption(em: Emitter, node: CarrierNode) -> None:
    """`figcaption`: a `Caption` paragraph, where it stands in the figure."""
    em.new_paragraph("Caption")
    em.inline_children(node)
