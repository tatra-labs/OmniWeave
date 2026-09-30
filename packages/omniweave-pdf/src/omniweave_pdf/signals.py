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
| `unit.encrypted` | `gate.encrypted` | pdfium opens it with no password (ADR-15 D15.2) |
| `corpus.is_form` | `gate.form-admits-fields` | `FPDF_GetFormType` is not `FORMTYPE_NONE` |
| `decode.char_count` | `decode.pdf-text-layer` | `FPDFText_CountChars`, summed (05:2242) |

A key this module is asked for and does not compute is left out of the answer, and the child
reports it unavailable by name. `ink.tiles`, the LOCAL group's one key, is the case that happens:
it needs a raster, and a scanned page reaches it only after its free group is spent.

## `decode.char_count` is the document's, because the router's part is the document

The row's scope is `part`, and a PDF's parts are its pages (02:479's `unit_part='p1'..'p42'`). The
router routes one decision per unit, under `expand.UNIDENTIFIED_PART`, so the part it asks about is
the whole document and the count is summed over every page.

## `unit.encrypted` is whether the file OPENS, not whether it carries `/Encrypt`

Detection's trailer scan (ADR-15 D15.1) says a PDF is encrypted. That is not the question
`gate.encrypted` needs answered: an owner-password-only PDF -- print or copy restrictions, and
nothing else -- carries `/Encrypt` and opens with the empty password, and 05:2239's scan alone would
refuse it where the build had always read it. D15.2 makes the key this provider's for a PDF, so the
child that already opens the file for `unit.part_count` answers it: `False` when pdfium opens the
bytes, `True` when pdfium refuses them for want of a password. The second is a VALUE, not a raise:
a raise refuses the whole group, which D579 holds for ever under gate 5, and a document that needs a
password is an answer, not a failure to compute one.

**With a password (D15.3, D15.4) it is whether the file opens with it.** The host sends the one
`[ingest] password_file` maps the unit to, on the child's stdin. pdfium is asked with no password
first, so an owner-only file answers as it does without one, and the password is tried only when
that is refused: a file it opens answers `False`, which is 05:476's *"`unit.encrypted` is
recomputed as `false` after the successful open"*, and a wrong password leaves it `True`.

On a document with a text layer on some
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

__all__ = ["COMPUTES", "ENCRYPTED", "compute", "needs_password"]


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


ENCRYPTED: Final[str] = "unit.encrypted"


def _opened(document: pdfium.PdfDocument) -> bool:
    """`unit.encrypted` for a document pdfium has opened: it needed no password (ADR-15 D15.2)."""
    del document
    return False


COMPUTES: Final[dict[str, Callable[[pdfium.PdfDocument], Scalar]]] = {
    "unit.part_count": _part_count,
    ENCRYPTED: _opened,
    "corpus.is_form": _is_form,
    "decode.char_count": _char_count,
}
"""Every key this module answers, and how. The keys are `signals.toml` rows; the rest of that file's
thirteen `pdfium` rows are declared and have no computer yet."""


def compute(raw: bytes, keys: Sequence[str], *, password: str | None = None) -> dict[str, Scalar]:
    """The asked-for keys this module computes, from one PDF's bytes. The others are absent.

    A document pdfium refuses for want of a password answers `unit.encrypted = True` when that key
    was asked, and nothing else: every other key needs the open document (ADR-15 D15.2). With
    `password`, a document that opens with it answers every key, `unit.encrypted = False` among
    them (D15.3).

    Raises:
        pdfium.PdfiumError: pdfium will not open the bytes, and not for a password, or the
            password refusal came where `unit.encrypted` was not asked. The child reports every
            asked key unavailable with pdfium's own message, which is what
            `decode.pdf-text-layer`'s `on_unknown = "defer"` then degrades to `skip` on (05:1130).
    """
    wanted = [key for key in keys if key in COMPUTES]
    if not wanted:
        return {}
    try:
        document = _open(raw, password)
    except pdfium.PdfiumError as exc:
        if ENCRYPTED in wanted and needs_password(exc):
            return {ENCRYPTED: True}
        raise
    try:
        return {key: COMPUTES[key](document) for key in wanted}
    finally:
        document.close()


def _open(raw: bytes, password: str | None) -> pdfium.PdfDocument:
    """With no password, then with `password` only if pdfium refused for want of one."""
    try:
        return pdfium.PdfDocument(raw)
    except pdfium.PdfiumError as exc:
        if password is None or not needs_password(exc):
            raise
    return pdfium.PdfDocument(raw, password=password)


def needs_password(exc: Exception) -> bool:
    """pdfium's refusal for want of a password. The wrapper raises one type for every refusal,
    so this reads its text, as `driver.PdfDriver._open` does."""
    message = str(exc).lower()
    return "password" in message or "encrypt" in message
