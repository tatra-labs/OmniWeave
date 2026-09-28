"""The `pdfium` provider's computer: three of `signals.toml`'s rows, answered from the source bytes.

05-ingest-and-routing.md section 5 registers a provider as *"an `omniweave.signals` entry point plus
a `signals.toml`"* (05:2044) and says nothing about how its values are computed. This module is the
compute half, located the way the declaration is: a fixed filename beside `signals.toml`, in the
package the entry point names. `omniweave_core.host.signals` imports it in a child process, and
nothing in the supervisor ever does -- pdfium is *"the largest memory-unsafe surface in the shipped
set"* and 14:469 makes `subproc` *"the floor for the PDF path"*, which a routing signal read from
the same bytes does not get to step under (D628).

## The three keys, and the rows that demand them

The router this build runs is `GATE` then `DECODE`, `text` lane, `select` phase (`run/routing.py`),
and the free groups of those two plans read three keys this provider serves for a PDF:

| key | rule | computation |
|---|---|---|
| `unit.part_count` | `gate.too-many-parts` | `FPDF_GetPageCount` (05:2199) |
| `corpus.is_form` | `gate.form-admits-fields` | `FPDF_GetFormType` is not `FORMTYPE_NONE` |
| `decode.char_count` | `decode.pdf-text-layer` | `FPDFText_CountChars`, summed (05:2242) |

A key this module is asked for and does not compute is left out of the answer, and the child
reports it unavailable by name. `ink.tiles`, the LOCAL group's one key, is the case that happens:
it needs a raster, and a scanned page reaches it only after its free group is spent.

## `decode.char_count` is the document's, because the router's part is the document

The row's scope is `part`, and a PDF's parts are its pages (02:479's `unit_part='p1'..'p42'`). The
router routes one decision per unit, under `expand.UNIDENTIFIED_PART`, so the part it asks about is
the whole document and the count is summed over every page. On a document with a text layer on some
pages and none on others the sum is positive and `decode.pdf-text-layer` routes all of it to
pdfium, which then reports each empty page with a `diag` (the driver's own docstring). A per-page
decision is what 05:1089's loop over parts would make, and it is not built.

`FPDFText_CountChars` counts the `\\r\\n` pairs pdfium synthesises at line ends (`glyphs.py`'s
module docstring), so a page with one line of text counts more than its visible characters. The
rules compare against zero and nothing else, and a page with no text layer counts zero.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from omniweave_ports.types import Scalar

__all__ = ["COMPUTES", "compute"]


def _part_count(document: pdfium.PdfDocument) -> int:
    return len(document)


def _is_form(document: pdfium.PdfDocument) -> bool:
    return int(document.get_formtype()) != pdfium_raw.FORMTYPE_NONE


def _char_count(document: pdfium.PdfDocument) -> int:
    total = 0
    for index in range(len(document)):
        page = document[index]
        try:
            textpage = page.get_textpage()
            try:
                total += max(0, int(textpage.count_chars()))
            finally:
                textpage.close()
        finally:
            page.close()
    return total


COMPUTES: Final[dict[str, Callable[[pdfium.PdfDocument], Scalar]]] = {
    "unit.part_count": _part_count,
    "corpus.is_form": _is_form,
    "decode.char_count": _char_count,
}
"""Every key this module answers, and how. The keys are `signals.toml` rows; the rest of that file's
thirteen `pdfium` rows are declared and have no computer yet."""


def compute(raw: bytes, keys: Sequence[str]) -> dict[str, Scalar]:
    """The asked-for keys this module computes, from one PDF's bytes. The others are absent.

    Raises:
        pdfium.PdfiumError: pdfium will not open the bytes. The child reports every asked key
            unavailable with pdfium's own message, which is what `decode.pdf-text-layer`'s
            `on_unknown = "defer"` then degrades to `skip` on (05:1130).
    """
    wanted = [key for key in keys if key in COMPUTES]
    if not wanted:
        return {}
    document = pdfium.PdfDocument(raw)
    try:
        return {key: COMPUTES[key](document) for key in wanted}
    finally:
        document.close()
