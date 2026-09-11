"""`parse.pdf.pdfium` — the born-digital PDF text layer, addressed so a quote can be re-proved.

16-roadmap.md:485 is the work item: "born-digital text runs, glyph geometry, INV-10's `glyphs`
branch with a recorded `os_extractor`, `Quad.from_driver` as the sole constructor, the char-stream
reading order".

02-architecture.md:266 draws the boundary the other way and is worth quoting, because what this
driver does NOT do is a design decision rather than an omission: it does "the text layer and glyph
runs (INV-10's `glyphs` branch), page geometry, page rasters at a requested DPI" and **not** "layout
classification -- there is no licence-clean detector at release 1 (F4), so `layout.class_hist` is
absent and every affected decision records `cause = "layout_unavailable"`".

## What this driver is for, in one sentence

03-document-model.md:1468: "A PDF paragraph has no byte range in the content stream. Without a
glyph-run address, `parse.pdf.pdfium` could never produce a `VERBATIM` block, and with
`parse.office.anydoc` honestly declaring `origin_span = "none"` the `VERBATIM` tier would ship with
**no producer at all**." This is that producer.

## One block per LINE, and the reason is `verbatim`

The obvious thing to do with a PDF text layer is join lines into paragraphs. This driver does not,
and the reason is INV-10 rather than taste: a block's `quote` may be `verbatim` only when the
recorded address re-extracts to the block's text under NFC (03:1419). Joining two lines with a
space produces text that is not any slice of the glyph index space, so a reflowing driver's blocks
are `normalized` at best and its card's `origin_span` claim buys nothing.

So a block is a line, its text is exactly `document_text[a : a+len]`, and `quote = "verbatim"` is
true by construction rather than by assertion. Paragraph assembly is a later pass's job over blocks
that already carry addresses -- which is the direction 03's pipeline runs, and it can reflow freely
because the addresses survive on the blocks it merges.

## `char_stream`, which is a measurement rather than a preference

`reading_order = "char_stream"` is the fourth of five rungs (03:507, `raster < learned <
model_emitted < char_stream < source`) and 03:2183 says why the ladder is ordered that way: "it is
marker's measurement: a char-stream order beat a learned layout head 75% to 56% on olmocr-bench's
order tests". 16-roadmap.md:485 makes that "the floor we may not ship below". Emitting blocks in
glyph-index order IS a char-stream order -- there is no reordering step to get wrong, and none to
justify.

## The quad, and why the driver does not build one

`Quad.from_driver` lives in `omniweave_core.model.spans` and `tools/layers.toml` gives
`omniweave_pdf = ["omniweave_ports"]`, so this driver may not import it -- which is the right
outcome and not an obstacle. `spans.py:21` says the transform happens "once, at the boundary,
inside `Quad.from_driver`", and the boundary is the host's. The driver therefore hands over points
in its OWN frame and declares that frame on the page record, which is exactly what 03:1393 says the
page record is for.

PDF user space is `bottomleft` and `pt` (03:1385's first row), so every quad here is four `(x, y)`
pairs in points with y increasing upward. **The page record also carries `quad_unit` and
`quad_dpi`**, which the plan's own record shape does not: ledger D120 records why. `quad_origin`
alone is two of the five inputs `Quad.from_driver` takes, `origin` does not determine `unit`
(03:1385 gives `topleft` to both `emu` and `px`), and for `px` the missing `dpi` is
`OW_QUAD_NO_DPI`. `test_pdf_geometry.py` feeds `Quad.from_driver` from the page record's fields and
nothing else, which is the audit 03:1394 promises.

## A page with no text layer

`NEEDS_OCR` is raised only when EVERY page is empty, because that is the document-level claim the
`FailureClass` makes. A document with some empty pages emits those pages with no blocks and one
`diag` per page, which is INV-13's per-page escalation seen from the driver's side: the host decides
whether to send those pages to an OCR driver, and it can only decide that if this driver reports
them rather than failing the document out from under it.

Specified in 16-roadmap.md W3.5; 02-architecture.md section 2 row 42; 03-document-model.md
sections 7.1, 7.2 and 8.3.
"""

from __future__ import annotations

import ctypes
import json
from typing import TYPE_CHECKING, Any, ClassVar

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from omniweave_ports import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    FormatGuess,
    ProbeStatus,
    ProbeVerdict,
)

from omniweave_pdf.glyphs import EXTRACTOR, page_texts, pdfium_build, verify

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_ports.detect import StreamHint
    from omniweave_ports.types import DriverIO, PartSelector, ProbeEnv, Scalar, UnitRef

ACHIEVED: dict[str, object] = {
    "spatial": "block_bbox",
    "origin_span": "exact",
    "text_span": False,
    "marks": False,
    "reading_order": "char_stream",
    "sections": "none",
    "tables": "none",
    "math": [],
    "assets": "none",
    "asset_origin": False,
    "notes": "none",
    "confidence": "none",
    "furniture": "destroyed",
    "round_trip": "text",
    "forfeits": [],
}
"""The fifteen keys of `achieved`, exactly as `driver.toml` declares them.

`spatial = "block_bbox"` and `origin_span = "exact"` together are 03:1558's row -- "both an origin
address and a polygon (`parse.pdf.pdfium` on a born-digital page)" -- whose consequence the plan
states as "full: byte-exact quoting **and** citation-to-pixel".

`sections = "none"` rather than `outline_from_source`: 03:3118 says this driver is
"`outline_from_source` at best", and *at best* is a ceiling rather than a claim. Reading the PDF
outline is real work this driver does not yet do, and a card may not declare a rung its code does
not reach -- the `capability` suite's P15 would catch it on the first fixture with no bookmarks.

`furniture = "destroyed"` for the same reason: separating a running header from body text is
layout work, and 02:266 puts layout classification outside this driver at release 1."""

PART = "pdf/source.pdf"
"""The one retained part's path. `retain = True`, because `origin_span = "exact"` is a claim about
a document that must still be there to re-extract from."""

_PDF_MAGIC = b"%PDF-"
_HEAD_WINDOW = 65_536
_NAMED_CONFIDENCE = 0.95
_UNNAMED_CONFIDENCE = 0.6
_PDF_SUFFIXES = (".pdf",)
_MPT_PER_PT = 1000
_SEPARATORS = "\r\n"
_DEFAULT_MIN_CHARS = 1


class PdfiumParser:
    """Born-digital PDF text runs, one block per line, each addressed in the glyph index space."""

    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """pdfium is a bundled binary, so the only question is whether the wheel imported.

        `detail` names the build rather than saying "ok", because 04:1586's example tombstone --
        "pdfium 6.x changes glyph run grouping" -- makes the binary's version the thing a reader
        needs when a glyph address stops re-verifying. `UNAVAILABLE` fills `missing` and `fix_hint`
        as the Protocol requires; there is no `DEGRADED` state, because a half-loaded pdfium is not
        a thing that happens.
        """
        del env
        try:
            build = pdfium_build()
        except Exception as exc:  # a broken wheel is UNAVAILABLE, not a crash at import time.
            return ProbeVerdict(
                status=ProbeStatus.UNAVAILABLE,
                detail=f"pypdfium2 present but unusable: {type(exc).__name__}: {exc}",
                missing=("pypdfium2",),
                fix_hint="uv pip install --force-reinstall pypdfium2",
            )
        return ProbeVerdict(
            status=ProbeStatus.OK,
            detail=f"{EXTRACTOR}, bundled pdfium {build}",
        )

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY: no file is opened, no model is loaded, no document is parsed.

        `min_chars` is the one knob and it does one thing: a line whose stripped length is below it
        contributes no block. The default of 1 drops only lines that are entirely whitespace, which
        pdfium emits for a blank line in the content stream and which would otherwise become an
        empty `verbatim` block -- an address with nothing at the end of it.

        **`dpi` is deliberately absent** even though 04-driver-system.md:2779 prints
        `[drivers."parse.pdf.pdfium"] config = { dpi = 192 }` as an operator-config example. `dpi`
        belongs to the page-raster half of 02:266's row, which 16-roadmap.md:485's W3.5 cell does
        not carry; declaring a key this code ignores would be a card claiming a knob that turns
        nothing.
        """
        self.min_chars = int(config.get("min_chars", _DEFAULT_MIN_CHARS))
        if self.min_chars < 0:
            raise DriverError(
                cls=FailureClass.DRIVER_BUG,
                message=f"min_chars={self.min_chars}; a length may not be negative",
            )

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        """`%PDF-` at the head, ranked by whether the filename agrees. Advances nothing.

        The magic is decisive: a file that does not begin `%PDF-` within the first few bytes is not
        a PDF this driver will open, so `()` -- a legitimate "not mine" -- is the honest answer
        rather than a low-confidence guess. Some producers emit junk before the header, which is
        why the search is over a window rather than a prefix test, and the window is small because
        a header a kilobyte in is a file `pdfium` itself will refuse.
        """
        window = 1024
        if _PDF_MAGIC not in head[:window]:
            return ()
        name = (hint.filename or "").lower()
        confidence = _NAMED_CONFIDENCE if name.endswith(_PDF_SUFFIXES) else _UNNAMED_CONFIDENCE
        return (
            FormatGuess(
                media_type="application/pdf",
                format_token="pdf",  # noqa: S106 -- a format token, not a secret.
                confidence=confidence,
                consumed_bytes=len(head),
            ),
        )

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        """Emit `owdoc-fragment/1`: one doc, one part, one page row per page, one block per line.

        NO `max_input_bytes` CHECK: the host refused the unit before INVOKE (DR20). NO
        `max_output_bytes` check either: `ArtifactRef.of()` meters it once and raises `TOO_LARGE`
        naming the knob.

        Raises:
            DriverError: `CORRUPT_INPUT` for bytes pdfium will not open; `ENCRYPTED` for a document
                whose content needs a password; `NEEDS_OCR` when no page carries a text layer;
                `TIMEOUT` when cancelled, whose `retry_after_ms` is REQUIRED because the class is
                transient.
        """
        del parts
        with io.blobs.open(unit.content_sha256) as handle:
            raw = handle.read()

        document = self._open(raw)
        try:
            records = list(self._records(document, unit, raw, io))
        finally:
            document.close()

        body = "".join(
            json.dumps(record, separators=(",", ":")) + "\n" for record in records
        ).encode("utf-8")
        ref = ArtifactRef.of("doc_fragment", body, io)
        return DriverResult(
            outcome="ok", produced=(ref,), metrics=DriverMetrics(bytes_read=len(raw))
        )

    def _open(self, raw: bytes) -> pdfium.PdfDocument:
        """Open, and turn pdfium's two refusals into the two `FailureClass` members that mean them.

        `PdfiumError` covers both a malformed file and an encrypted one, and they are different
        answers to the host: `CORRUPT_INPUT` is permanent for these bytes, while `ENCRYPTED` tells
        an operator that a password would fix it. The discrimination is on pdfium's own error text
        because the wrapper raises one exception type for both.
        """
        try:
            document = pdfium.PdfDocument(raw)
            len(document)  # forces the page tree; a truncated xref fails here, not at open.
        except pdfium.PdfiumError as exc:
            message = str(exc).lower()
            if "password" in message or "encrypt" in message:
                raise DriverError(
                    cls=FailureClass.ENCRYPTED,
                    message=f"pdfium will not open this document: {exc}",
                ) from None
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"pdfium will not open this document: {exc}",
            ) from None
        except Exception as exc:
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"{type(exc).__name__} opening the document: {exc}",
            ) from None
        return document

    def _records(
        self,
        document: pdfium.PdfDocument,
        unit: UnitRef,
        raw: bytes,
        io: DriverIO,
    ) -> Iterator[dict[str, Any]]:
        """The fragment, in order: `doc`, `part`, then per page a `page` and its blocks."""
        page_count = len(document)
        yield {
            "t": "doc",
            "format": "pdf",
            "media_type": "application/pdf",
            "page_count": page_count,
            "achieved": ACHIEVED,
        }
        yield {
            "t": "part",
            "path": PART,
            "sha256": unit.content_sha256,
            "byte_len": len(raw),
            "retain": True,
        }

        blocks = 0
        texted_pages = 0
        per_page: dict[str, dict[str, int]] = {}
        for part in page_texts(document):
            if io.cancelled():  # CHECK AT EVERY LOOP TOP
                raise DriverError(
                    cls=FailureClass.TIMEOUT,
                    message=f"cancelled by generation at page {part.index}",
                    retry_after_ms=0,
                )
            page = document[part.index]
            width, height = page.get_size()
            rotation = page.get_rotation()
            yield self._page_record(part.index, width, height, rotation)

            if part.length == 0:
                yield {
                    "t": "diag",
                    "code": "OW_PDF_NO_TEXT_LAYER",
                    "severity": "warning",
                    "component": "parse.pdf.pdfium",
                    "message": "this page carries no text layer; it is a candidate for OCR",
                    "page": part.index,
                    "part": PART,
                    "detail": {},
                    "fatal": False,
                }
                per_page[str(part.index)] = {"blocks": 0}
                page.close()
                continue

            texted_pages += 1
            on_page = 0
            textpage = page.get_textpage()
            try:
                for line in _lines(part.text):
                    if len(line.text.strip()) < self.min_chars:
                        continue
                    blocks += 1
                    on_page += 1
                    yield self._block_record(
                        tmp=f"b{blocks}",
                        page=part.index,
                        text=line.text,
                        start=part.start + line.offset,
                        quad=_quad(textpage, line.offset, len(line.text), height),
                    )
            finally:
                textpage.close()
                page.close()
            per_page[str(part.index)] = {"blocks": on_page}
            io.progress(done=part.index + 1, total=page_count)

        if page_count and texted_pages == 0:
            raise DriverError(
                cls=FailureClass.NEEDS_OCR,
                message=(
                    f"none of this document's {page_count} pages carries a text layer; "
                    f"a rendering driver is the one that can read it"
                ),
            )
        yield {"t": "end", "status": "ok", "page_stats": per_page}

    def _page_record(
        self, index: int, width: float, height: float, rotation: int
    ) -> dict[str, Any]:
        """One `page` row, carrying every input `Quad.from_driver` takes except the points.

        `quad_unit` and `quad_dpi` are not in the record shape the plan prints; ledger D120 is the
        entry and the reason is that `quad_origin` alone cannot support the re-derivation 03:1394
        claims for it. `quad_dpi` is null because PDF user space is `pt`, where a dpi is meaningless
        -- recorded as null rather than omitted, so a reader can tell "not applicable" from "not
        recorded".

        `w_mpt`/`h_mpt` are "the unrotated page box" (03:1395). `page.get_size()` returns exactly
        that, and `rotation` is carried beside it as the display rotation.
        """
        return {
            "t": "page",
            "page": index,
            "page_kind": "page",
            "w_mpt": round(width * _MPT_PER_PT),
            "h_mpt": round(height * _MPT_PER_PT),
            "quad_origin": "bottomleft",
            "quad_unit": "pt",
            "quad_dpi": None,
            "rotation": rotation,
            "method": "text_layer",
        }

    def _block_record(
        self,
        *,
        tmp: str,
        page: int,
        text: str,
        start: int,
        quad: list[float] | None,
    ) -> dict[str, Any]:
        """One `block` row. `quote = "verbatim"` is true by construction, not by assertion.

        `text` is `document_text[start : start + len(text)]` because that is where it came from, so
        INV-10's `glyphs` predicate holds without the driver doing anything to make it hold. The
        `os` keys are `start` and `length` rather than the archive's `a` and `len`:
        03-document-model.md:632-634 makes `owdoc-fragment/1` "a different wire" using "long,
        spelled-out keys", and says the two key sets are "deliberately disjoint in spelling so that
        a record cannot be misread as the other format".
        """
        return {
            "t": "block",
            "tmp": tmp,
            "parent": None,
            "page": page,
            "kind": "paragraph",
            "layer": "body",
            "text": text,
            "quote": "verbatim",
            "trust": "extracted",
            "method": "text_layer",
            "os": {
                "k": "glyphs",
                "part": PART,
                "extractor": EXTRACTOR,
                "start": start,
                "length": len(text),
            },
            "quad": quad,
            "marks": [],
            "payload": None,
        }

    @staticmethod
    def verify_origin(part: bytes, origin: dict[str, Any], text: str) -> tuple[bool, str]:
        """The conformance kit's re-verification hook: re-extract this address and compare.

        `omniweave_conform.suites.capability.ORIGIN_VERIFIER` names this method, and the kit calls
        it for any `origin_span` branch it cannot read unaided. `bytes` it can; `glyphs` it cannot,
        because reading the glyph index space means running pdfium -- which is this driver's
        dependency and not the kit's.

        Returns `(ok, reason)`, and the reason distinguishes the three answers rather than
        collapsing them: a different extractor is not a mismatch, an unresolvable address is not a
        mismatch, and only a resolved address whose text differs is a finding about this driver.
        `glyphs.verify()` is where that distinction lives, and this method is the adapter from the
        fragment's `os` record to its arguments.

        A `staticmethod` because it reads nothing from the instance: the address carries everything
        the re-extraction needs, which is exactly the property INV-10 is asserting. A hook that
        needed parse state would be re-verifying against the parse rather than against the part.
        """
        if origin.get("k") != "glyphs":
            return False, f"this driver addresses blocks by glyphs, not {origin.get('k')!r}"
        return verify(
            part,
            int(origin.get("start", -1)),
            int(origin.get("length", -1)),
            text,
            str(origin.get("extractor", "")),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """The host calls this BEFORE caching. A PDF of blank pages is legitimately empty.

        An `ok` that fails here becomes `FAILED_PERMANENT(EMPTY_RESULT)`, so an empty success is
        never memoised and never served from cache forever.
        """
        return b'"t":"block"' in ref.head(_HEAD_WINDOW)


class _Line:
    """One line of a page's text, and its offset within that page's character sequence."""

    __slots__ = ("offset", "text")

    def __init__(self, offset: int, text: str) -> None:
        self.offset = offset
        self.text = text


def _lines(text: str) -> Iterator[_Line]:
    """Split on runs of `\\r` and `\\n`, keeping each line's offset in the page's index space.

    A RUN, not a single character: pdfium synthesises `\\r\\n` pairs at line ends, and splitting on
    one of the two would leave the other at the head of the next line -- inside a block's text,
    inside its recorded range, and therefore inside what `verbatim` claims. The separators
    themselves are never part of any block's range, which is what keeps every block's text a
    contiguous slice with nothing skipped and nothing doubled.
    """
    cursor = 0
    length = len(text)
    while cursor < length:
        while cursor < length and text[cursor] in _SEPARATORS:
            cursor += 1
        start = cursor
        while cursor < length and text[cursor] not in _SEPARATORS:
            cursor += 1
        if cursor > start:
            yield _Line(start, text[start:cursor])


def _quad(
    textpage: pdfium.PdfTextPage, offset: int, length: int, page_h: float
) -> list[float] | None:
    """The bounding quadrilateral of a line's characters, in PDF user space.

    Four `(x, y)` pairs in points with y increasing upward, corner order top-left then clockwise IN
    THE DRIVER'S FRAME -- `Quad.from_driver` "re-orders whatever the driver handed it" (03:1400),
    so the order here is a courtesy rather than a contract, and the frame is the contract.

    Degenerate boxes are excluded. pdfium gives a synthesised separator a zero-area box at the end
    of the line it terminates, and including one would stretch a quad to a point that no glyph
    occupies. Returns `None` when every box was degenerate, which is a line of glyphs that render
    nothing -- `spatial` then has nothing to say about it, and saying nothing is the honest form.
    """
    left = ctypes.c_double()
    right = ctypes.c_double()
    bottom = ctypes.c_double()
    top = ctypes.c_double()
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    seen = False
    for index in range(offset, offset + length):
        if not pdfium_raw.FPDFText_GetCharBox(textpage.raw, index, left, right, bottom, top):
            continue
        if left.value == right.value and bottom.value == top.value:
            continue
        seen = True
        x0 = min(x0, left.value)
        x1 = max(x1, right.value)
        y0 = min(y0, bottom.value)
        y1 = max(y1, top.value)
    if not seen:
        return None
    del page_h  # the flip is `Quad.from_driver`'s; this frame is the driver's own.
    return [x0, y1, x1, y1, x1, y0, x0, y0]
