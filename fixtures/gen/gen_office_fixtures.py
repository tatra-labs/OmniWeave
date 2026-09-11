#!/usr/bin/env python3
"""Generate `parse.office.anydoc`'s conformance corpus: sixteen documents, written by hand.

Every file this script writes is assembled from XML and ZIP bytes here, with no office suite, no
converter and no library beyond the standard `zipfile`. That is a deliberate choice and it has
three reasons.

1. **Provenance.** 11-repo-layout.md's Tier A rule is "one `.meta.toml` per file, four admissible
   provenances". A document produced by this script has the simplest admissible provenance there
   is -- it was written here, and the script is the record of exactly what is in it.
2. **Determinism.** Every ZIP entry gets a fixed timestamp and `ZIP_STORED`, so the bytes are a
   function of this file alone. `EXPECTED.sha256` is then a real check rather than a snapshot of
   whichever machine ran last, and 13-quality.md:586's rule -- a generator change must be a
   one-line visible diff and never a silent corpus change -- holds.
3. **A fixture must be a CASE, not a document.** Each file below exists to make one thing the
   driver does observable: a merged cell, a footnote with its reference site, an embedded image
   with an `origin_part`, OMML math, a nesting depth that trips anydoc's own `max_xml_depth`. A
   real document produced by a real word processor carries hundreds of bytes of settings and one
   accident of whatever version wrote it.

Usage:

    uv run python fixtures/gen/gen_office_fixtures.py
    uv run python fixtures/gen/gen_office_fixtures.py --out <dir>   # default: the office package

Specified in 16-roadmap.md W3.4; 13-quality.md section 4 (fixture tiers and provenance).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "packages" / "omniweave-office" / "fixtures"
ZIP_DATE = (2026, 1, 1, 0, 0, 0)

# A 1x1 transparent PNG, 70 bytes. The smallest thing that is unambiguously an image, so
# `Asset.media_type` is decided by content and `origin_part` by where it sits in the package.
DOT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"


def zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    """A ZIP whose bytes depend only on `entries`. Stored, fixed dates, no extra fields."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def content_types(*overrides: str) -> bytes:
    body = "".join(overrides)
    return (
        XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>' + body + "</Types>"
    ).encode()


def rels(*entries: str) -> bytes:
    body = "".join(entries)
    return (
        XML
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + body
        + "</Relationships>"
    ).encode()


def rel(rid: str, kind: str, target: str, mode: str = "") -> str:
    extra = f' TargetMode="{mode}"' if mode else ""
    return f'<Relationship Id="{rid}" Type="{R}/{kind}" Target="{target}"{extra}/>'


# ---------------------------------------------------------------------------
# docx -- the one fixture that carries every feature the card declares
# ---------------------------------------------------------------------------


def docx_rich() -> bytes:
    """One DOCX exercising all seven non-trivial `[capability.parse]` rows at once.

    Headings at two levels (`sections = outline_from_source`), styled runs and a hyperlink and a
    bookmark (`marks = true`), a merged-cell table (`tables = cells_with_spans`), an OMML formula
    both displayed and inline (`math = ["latex"]`), an embedded PNG (`assets = "bytes"` and
    `asset_origin = true`), and a footnote with its reference site (`notes = "linked"`).

    One file rather than seven, because the `capability` suite asserts `achieved <= declared` per
    fixture: a corpus of single-feature documents would prove each row in isolation and never once
    exercise the card as a whole.
    """
    drawing = (
        "<w:r><w:drawing>"
        f'<wp:inline xmlns:wp="{WP}"><wp:extent cx="9525" cy="9525"/>'
        '<wp:docPr id="1" name="Picture 1" descr="a single grey dot"/>'
        f'<a:graphic xmlns:a="{A}"><a:graphicData uri="{PIC}">'
        f'<pic:pic xmlns:pic="{PIC}"><pic:nvPicPr>'
        '<pic:cNvPr id="0" name="dot.png" descr="a single grey dot"/><pic:cNvPicPr/>'
        f'</pic:nvPicPr><pic:blipFill><a:blip xmlns:r="{R}" r:embed="rId3"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx='9525' cy='9525'/></a:xfrm>"
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
    )
    omath_display = (
        f'<m:oMathPara xmlns:m="{M}"><m:oMath><m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e>'
        "<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup>"
        "<m:r><m:t>+1</m:t></m:r></m:oMath></m:oMathPara>"
    )
    omath_inline = (
        f'<m:oMath xmlns:m="{M}"><m:f><m:num><m:r><m:t>a</m:t></m:r></m:num>'
        "<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath>"
    )
    cell = (
        '<w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
        "<w:p><w:r><w:t>Total across both quarters</w:t></w:r></w:p></w:tc>"
    )
    plain = "<w:tc><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:tc>"
    table = (
        "<w:tbl><w:tblPr/><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>"
        '<w:tr><w:trPr><w:tblHeader w:val="true"/></w:trPr>'
        + plain.format("Quarter")
        + plain.format("Revenue")
        + "</w:tr><w:tr>"
        + plain.format("Q1")
        + plain.format("120")
        + "</w:tr><w:tr>"
        + cell
        + "</w:tr></w:tbl>"
    )
    document = (
        XML + f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>'
        '<w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
        '<w:bookmarkStart w:id="1" w:name="top"/><w:bookmarkEnd w:id="1"/>'
        "<w:r><w:t>Quarterly report</w:t></w:r></w:p>"
        '<w:p><w:r><w:t xml:space="preserve">Plain, </w:t></w:r>'
        "<w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>"
        '<w:r><w:t xml:space="preserve">, </w:t></w:r>'
        "<w:r><w:rPr><w:i/></w:rPr><w:t>italic</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> and </w:t></w:r>'
        "<w:r><w:rPr><w:strike/></w:rPr><w:t>struck</w:t></w:r>"
        '<w:r><w:t xml:space="preserve">. See </w:t></w:r>'
        '<w:hyperlink r:id="rId2"><w:r><w:t>the site</w:t></w:r></w:hyperlink>'
        '<w:r><w:t xml:space="preserve">.</w:t></w:r>'
        '<w:r><w:footnoteReference w:id="2"/></w:r></w:p>'
        '<w:p><w:pPr><w:outlineLvl w:val="1"/></w:pPr>'
        "<w:r><w:t>Figures</w:t></w:r></w:p>"
        "<w:p>" + omath_display + "</w:p>"
        '<w:p><w:r><w:t xml:space="preserve">The ratio </w:t></w:r>'
        + omath_inline
        + "</w:p>"
        + table
        + "<w:p>"
        + drawing
        + "</w:p>"
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
        "<w:r><w:t>first item</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
        "<w:r><w:t>second item</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    footnotes = (
        XML + f'<w:footnotes xmlns:w="{W}">'
        '<w:footnote w:id="2"><w:p><w:r><w:t>Unaudited figures.</w:t></w:r></w:p></w:footnote>'
        "</w:footnotes>"
    )
    numbering = (
        XML + f'<w:numbering xmlns:w="{W}">'
        '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0">'
        '<w:numFmt w:val="bullet"/><w:lvlText w:val="-"/></w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
        "</w:numbering>"
    )
    return zip_bytes(
        [
            (
                "[Content_Types].xml",
                content_types(
                    '<Override PartName="/word/document.xml" ContentType="application/vnd'
                    '.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                ),
            ),
            ("_rels/.rels", rels(rel("rId1", "officeDocument", "word/document.xml"))),
            ("word/document.xml", document.encode()),
            (
                "word/_rels/document.xml.rels",
                rels(
                    rel("rId2", "hyperlink", "https://example.invalid/report", "External"),
                    rel("rId3", "image", "media/dot.png"),
                    rel("rId4", "footnotes", "footnotes.xml"),
                    rel("rId5", "numbering", "numbering.xml"),
                ),
            ),
            ("word/footnotes.xml", footnotes.encode()),
            ("word/numbering.xml", numbering.encode()),
            ("word/media/dot.png", DOT_PNG),
        ]
    )


def docx_deep(depth: int = 400) -> bytes:
    """A DOCX whose body nests past anydoc's `max_xml_depth = 256`.

    The `limits` suite's whole question is whether a declared limit refuses at the read boundary
    rather than after the memory is spent, and on this driver every interesting limit is compiled
    into someone else's crate. This fixture is how that becomes observable from Python: 400 nested
    elements in a 6 KB file, which is a refusal and not an allocation.
    """
    inner = "<w:r><w:t>deep</w:t></w:r>"
    for _ in range(depth):
        inner = f"<w:smartTag>{inner}</w:smartTag>"
    document = XML + f'<w:document xmlns:w="{W}"><w:body><w:p>{inner}</w:p></w:body></w:document>'
    return zip_bytes(
        [
            (
                "[Content_Types].xml",
                content_types(
                    '<Override PartName="/word/document.xml" ContentType="application/vnd'
                    '.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                ),
            ),
            ("_rels/.rels", rels(rel("rId1", "officeDocument", "word/document.xml"))),
            ("word/document.xml", document.encode()),
        ]
    )


# ---------------------------------------------------------------------------
# xlsx / pptx
# ---------------------------------------------------------------------------


def xlsx_sheet() -> bytes:
    """A one-sheet workbook with a merged cell, so the grid has a `covered` slot."""
    sheet = (
        XML + f'<worksheet xmlns="{SS}"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Region</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Units</t></is></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>North</t></is></c>'
        '<c r="B2"><v>17</v></c></row>'
        '<row r="3"><c r="A3" t="inlineStr"><is><t>Total for all regions</t></is></c></row>'
        '</sheetData><mergeCells count="1"><mergeCell ref="A3:B3"/></mergeCells></worksheet>'
    )
    workbook = (
        XML + f'<workbook xmlns="{SS}" xmlns:r="{R}"><sheets>'
        '<sheet name="Summary" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    return zip_bytes(
        [
            (
                "[Content_Types].xml",
                content_types(
                    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd'
                    '.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd'
                    '.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                ),
            ),
            ("_rels/.rels", rels(rel("rId1", "officeDocument", "xl/workbook.xml"))),
            ("xl/workbook.xml", workbook.encode()),
            (
                "xl/_rels/workbook.xml.rels",
                rels(rel("rId1", "worksheet", "worksheets/sheet1.xml")),
            ),
            ("xl/worksheets/sheet1.xml", sheet.encode()),
        ]
    )


def pptx_deck() -> bytes:
    """One slide with a title, two bullets and a speaker note.

    The speaker note is here because of what anydoc does with it:
    `src/formats/pptx/mod.rs:207` pushes it as `Block::BlockQuote`, so it arrives in the Python
    model **indistinguishable from a real quotation**. The fixture makes that visible rather than
    leaving it as a claim in a docstring -- `Kind.SPEAKER_NOTE` has no producer on this path, and
    a test asserts the blockquote is what comes out.
    """

    def text_body(paragraphs: list[str]) -> str:
        runs = "".join(f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>" for text in paragraphs)
        return f"<p:txBody><a:bodyPr/><a:lstStyle/>{runs}</p:txBody>"

    def shape(name: str, body: str, placeholder: str = "") -> str:
        ph = f'<p:ph type="{placeholder}"/>' if placeholder else ""
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="{name}"/><p:cNvSpPr/>'
            f"<p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr/>{body}</p:sp>"
        )

    slide = (
        XML + f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        + shape("Title 1", text_body(["Pipeline status"]), "title")
        + shape("Content 2", text_body(["ingest is green", "compile is amber"]))
        + "</p:spTree></p:cSld></p:sld>"
    )
    notes = (
        XML + f'<p:notes xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        + shape("Notes 1", text_body(["Mention the backlog only if asked."]), "body")
        + "</p:spTree></p:cSld></p:notes>"
    )
    presentation = (
        XML + f'<p:presentation xmlns:p="{P}" xmlns:r="{R}">'
        '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst></p:presentation>'
    )
    return zip_bytes(
        [
            (
                "[Content_Types].xml",
                content_types(
                    '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd'
                    '.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                    '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd'
                    '.openxmlformats-officedocument.presentationml.slide+xml"/>'
                    '<Override PartName="/ppt/notesSlides/notesSlide1.xml" ContentType='
                    '"application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
                ),
            ),
            ("_rels/.rels", rels(rel("rId1", "officeDocument", "ppt/presentation.xml"))),
            ("ppt/presentation.xml", presentation.encode()),
            (
                "ppt/_rels/presentation.xml.rels",
                rels(rel("rId2", "slide", "slides/slide1.xml")),
            ),
            ("ppt/slides/slide1.xml", slide.encode()),
            (
                "ppt/slides/_rels/slide1.xml.rels",
                rels(rel("rId1", "notesSlide", "../notesSlides/notesSlide1.xml")),
            ),
            ("ppt/notesSlides/notesSlide1.xml", notes.encode()),
        ]
    )


# ---------------------------------------------------------------------------
# ODF: odt, ods, odp -- one package shape, three bodies
# ---------------------------------------------------------------------------

ODF_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
ODF_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
ODF_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
ODF_DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
ODF_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"


def odf(mimetype: str, body: str, *, encrypted: bool = False) -> bytes:
    """An ODF package. `mimetype` is stored first and uncompressed, as ODF 1.2 requires.

    `encrypted` writes the `<manifest:encryption-data>` element that ODF uses to declare an
    encrypted part, and nothing else: the content is not actually enciphered. That is enough and
    it is the point -- detection of encryption is a manifest read, so a fixture that declared it
    without doing it proves the refusal happens BEFORE any attempt to decode, which is what
    `FailureClass.ENCRYPTED` promises the operator.
    """
    encryption = (
        "<manifest:encryption-data "
        'manifest:checksum-type="SHA1/1K" manifest:checksum="AAAA">'
        '<manifest:algorithm manifest:algorithm-name="Blowfish CFB" '
        'manifest:initialisation-vector="AAAA"/>'
        '<manifest:key-derivation manifest:key-derivation-name="PBKDF2" '
        'manifest:salt="AAAA" manifest:iteration-count="1024"/>'
        "</manifest:encryption-data>"
        if encrypted
        else ""
    )
    manifest = (
        XML + f'<manifest:manifest xmlns:manifest="{ODF_MANIFEST}" manifest:version="1.2">'
        f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mimetype}"/>'
        '<manifest:file-entry manifest:full-path="content.xml" '
        f'manifest:media-type="text/xml">{encryption}</manifest:file-entry>'
        "</manifest:manifest>"
    )
    content = (
        XML + f'<office:document-content xmlns:office="{ODF_OFFICE}" xmlns:text="{ODF_TEXT}" '
        f'xmlns:table="{ODF_TABLE}" xmlns:draw="{ODF_DRAW}" office:version="1.2">'
        f"<office:body>{body}</office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        first = zipfile.ZipInfo("mimetype", date_time=ZIP_DATE)
        first.compress_type = zipfile.ZIP_STORED
        archive.writestr(first, mimetype.encode())
        for name, data in (
            ("META-INF/manifest.xml", manifest.encode()),
            ("content.xml", content.encode()),
        ):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            archive.writestr(info, data)
    return buffer.getvalue()


def odt_text() -> bytes:
    body = (
        "<office:text>"
        '<text:h text:outline-level="1">Field notes</text:h>'
        "<text:p>Two observations, in order.</text:p>"
        "<text:list><text:list-item><text:p>the first</text:p></text:list-item>"
        "<text:list-item><text:p>the second</text:p></text:list-item></text:list>"
        "</office:text>"
    )
    return odf("application/vnd.oasis.opendocument.text", body)


def ods_sheet() -> bytes:
    def cell(text: str, repeat: int = 1) -> str:
        span = (
            f' table:number-columns-spanned="{repeat}" table:number-rows-spanned="1"'
            if repeat > 1
            else ""
        )
        covered = "<table:covered-table-cell/>" * (repeat - 1)
        return (
            f'<table:table-cell office:value-type="string"{span}>'
            f"<text:p>{text}</text:p></table:table-cell>{covered}"
        )

    body = (
        '<office:spreadsheet><table:table table:name="Sheet1">'
        '<table:table-column table:number-columns-repeated="2"/>'
        f"<table:table-row>{cell('Site')}{cell('Uptime')}</table:table-row>"
        f"<table:table-row>{cell('eu-west')}{cell('99.9')}</table:table-row>"
        f"<table:table-row>{cell('Across every site', 2)}</table:table-row>"
        "</table:table></office:spreadsheet>"
    )
    return odf("application/vnd.oasis.opendocument.spreadsheet", body)


def odp_deck() -> bytes:
    body = (
        "<office:presentation>"
        '<draw:page draw:name="page1">'
        "<draw:frame><draw:text-box><text:p>Release plan</text:p></draw:text-box></draw:frame>"
        "<draw:frame><draw:text-box><text:p>one slide is enough</text:p>"
        "</draw:text-box></draw:frame>"
        "</draw:page></office:presentation>"
    )
    return odf("application/vnd.oasis.opendocument.presentation", body)


def odt_encrypted() -> bytes:
    return odf(
        "application/vnd.oasis.opendocument.text",
        "<office:text><text:p>never read</text:p></office:text>",
        encrypted=True,
    )


# ---------------------------------------------------------------------------
# epub, rtf, csv, and the two that are not documents at all
# ---------------------------------------------------------------------------


def epub_book() -> bytes:
    chapter = (
        "<?xml version='1.0' encoding='utf-8'?>"
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>One</title></head>'
        "<body><h1>Chapter one</h1>"
        "<p>A short paragraph with <strong>emphasis</strong> and "
        '<a href="chapter1.xhtml#later">a relative link</a>.</p>'
        "<hr/>"
        '<pre><code class="language-python">print("hi")\n</code></pre>'
        "<blockquote><p>Quoted material.</p></blockquote>"
        "<ul><li>alpha</li><li>beta</li></ul>"
        '<p id="later">The end.</p></body></html>'
    )
    opf = (
        XML + '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="bookid"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="bookid">urn:uuid:0000</dc:identifier>'
        "<dc:title>A very short book</dc:title><dc:language>en</dc:language>"
        "</metadata><manifest>"
        '<item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
        '</manifest><spine><itemref idref="c1"/></spine></package>'
    )
    container = (
        XML + '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        'version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        first = zipfile.ZipInfo("mimetype", date_time=ZIP_DATE)
        archive.writestr(first, b"application/epub+zip")
        for name, data in (
            ("META-INF/container.xml", container.encode()),
            ("OEBPS/content.opf", opf.encode()),
            ("OEBPS/chapter1.xhtml", chapter.encode()),
        ):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            archive.writestr(info, data)
    return buffer.getvalue()


def rtf_memo() -> bytes:
    return (
        r"{\rtf1\ansi\deff0{\fonttbl{\f0 Calibri;}}"
        r"\pard\b Memo\b0\par "
        r"\pard Plain text, then {\i italic} and {\b bold}.\par "
        r"\pard A second paragraph.\par}"
    ).encode("ascii")


def csv_rows() -> bytes:
    return b'region,units,note\r\nnorth,17,steady\r\nsouth,4,"a note, with a comma"\r\neast,0,\r\n'


def truncated_docx() -> bytes:
    """The first half of `rich.docx`. The central directory is gone, so detection itself fails."""
    whole = docx_rich()
    return whole[: len(whole) // 2]


def not_a_document() -> bytes:
    """Bytes with no container signature at all: `sniff()` returns `()`, a legitimate "not mine"."""
    return b"\x7fELF\x02\x01\x01\x00" + bytes(range(32))


# ---------------------------------------------------------------------------
# The legacy binary trio: doc, ppt, xls. A compound file, written here.
# ---------------------------------------------------------------------------
#
# These three exist because the card declares twelve media types and the conform `capability`
# suite requires every declared `format_tokens` pair to come back out of `sniff()` on some fixture.
# Without them the card declares `doc`, `ppt` and `xls` and no fixture ever shows the driver
# recognising one, which is a claim with no evidence -- and the suite says so.
#
# anydoc identifies all three by OLE STREAM NAME, not by a file signature: `WordDocument`,
# `PowerPoint Document`, `Workbook`/`Book` ([MS-DOC], [MS-PPT], [MS-XLS], and
# `vendor/anydoc/src/formats/detect.rs:60-64`). So the container has to be real even when the
# content is minimal, which is why there is a CFB writer here rather than a hand-pasted blob.

_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SECTOR = 512
_FREE, _END, _FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
_NOSTREAM = 0xFFFFFFFF
_MINI_CUTOFF = 4096


def compound_file(name: str, stream: bytes) -> bytes:
    """A v3 compound file holding one root and one named stream. No mini stream, ever.

    **The stream is padded to `_MINI_CUTOFF`**, and that is the one non-obvious constraint in the
    format: a stream SMALLER than 4096 bytes lives in the mini stream, addressed through a
    separate mini-FAT that this writer does not build. A reader then follows a mini-sector chain
    into a mini-FAT with no entries and reports the file as unreadable -- which is a bug in the
    fixture, not in the reader, and cost a debugging round to find. Padding is the honest fix:
    every record format here carries an explicit length, so trailing zeroes are past the last
    record a parser reads.
    """
    stream = stream.ljust(_MINI_CUTOFF, b"\x00")
    sectors = max(1, -(-len(stream) // _SECTOR))
    data_start = 2  # sector 0 is the FAT, sector 1 the directory

    fat = [_FREE] * (_SECTOR // 4)
    fat[0] = _FATSECT
    fat[1] = _END
    for index in range(sectors):
        at = data_start + index
        fat[at] = _END if index == sectors - 1 else at + 1

    def entry(entry_name: str, kind: int, child: int, start: int, size: int) -> bytes:
        raw = entry_name.encode("utf-16-le") + b"\x00\x00"
        return (
            raw.ljust(64, b"\x00")[:64]
            + struct.pack("<H", len(raw))
            + struct.pack("<BB", kind, 1)
            + struct.pack("<III", _NOSTREAM, _NOSTREAM, child)
            + b"\x00" * 16
            + struct.pack("<I", 0)
            + b"\x00" * 16
            + struct.pack("<IQ", start, size)
        )

    directory = entry("Root Entry", 5, 1, _END, 0) + entry(
        name, 2, _NOSTREAM, data_start, len(stream)
    )
    directory = directory.ljust(_SECTOR, b"\x00")

    header = bytearray(_SECTOR)
    header[0:8] = _CFB_MAGIC
    struct.pack_into("<HH", header, 0x18, 0x003E, 3)
    struct.pack_into("<H", header, 0x1C, 0xFFFE)
    struct.pack_into("<HH", header, 0x1E, 9, 6)
    struct.pack_into("<I", header, 0x2C, 1)
    struct.pack_into("<I", header, 0x30, 1)
    struct.pack_into("<I", header, 0x38, _MINI_CUTOFF)
    struct.pack_into("<I", header, 0x3C, _END)
    struct.pack_into("<I", header, 0x44, _END)
    struct.pack_into("<109I", header, 0x4C, *([0] + [_FREE] * 108))

    fat_sector = b"".join(struct.pack("<I", value) for value in fat)
    return bytes(header) + fat_sector + directory + stream.ljust(sectors * _SECTOR, b"\x00")


def _biff(record: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HH", record, len(payload)) + payload


def xls_sheet() -> bytes:
    """A real BIFF8 workbook: a globals substream, a worksheet, and four cells.

    BIFF is a flat record stream -- every record is `(id, length, payload)` -- which is why this
    is writable by hand where a `.doc` is not. `BOUNDSHEET` carries the ABSOLUTE stream offset of
    the worksheet's `BOF`, so the globals substream is built twice: once to learn its own length,
    once with the offset that length implies. That is the only forward reference in the format.

    The filler record before the globals `EOF` is what pads the stream past the compound file's
    4096-byte mini-stream cutoff. It carries a real length, so a reader skips it without knowing
    what it is -- which is BIFF's own forward-compatibility rule, used here on purpose.
    """
    strings = ["Region", "Units", "north"]

    def bof(kind: int) -> bytes:
        return _biff(0x0809, struct.pack("<HHHHII", 0x0600, kind, 0x0DBB, 0x07CC, 0, 0))

    def sst() -> bytes:
        body = struct.pack("<ii", len(strings), len(strings))
        for text in strings:
            body += struct.pack("<HB", len(text), 0) + text.encode("latin-1")
        return _biff(0x00FC, body)

    def boundsheet(position: int) -> bytes:
        raw = b"Sheet1"
        return _biff(0x0085, struct.pack("<IHBB", position, 0, len(raw), 0) + raw)

    def globals_at(position: int) -> bytes:
        filler = _biff(0x005C, bytes(4000))
        return bof(0x0005) + boundsheet(position) + sst() + filler + _biff(0x000A)

    head = globals_at(0)
    head = globals_at(len(head))
    sheet = (
        bof(0x0010)
        + _biff(0x0200, struct.pack("<IIHHH", 0, 2, 0, 2, 0))
        + _biff(0x00FD, struct.pack("<HHHI", 0, 0, 15, 0))
        + _biff(0x00FD, struct.pack("<HHHI", 0, 1, 15, 1))
        + _biff(0x00FD, struct.pack("<HHHI", 1, 0, 15, 2))
        + _biff(0x0203, struct.pack("<HHHd", 1, 1, 15, 17.0))
        + _biff(0x000A)
    )
    return compound_file("Workbook", head + sheet)


def ppt_deck() -> bytes:
    """A compound file with an empty `PowerPoint Document` stream.

    anydoc reads it as a valid presentation with nothing in it -- zero blocks, no error -- which
    is a real answer about a real document and the reason this fixture is worth having: an empty
    success is what `is_valid_nonempty()` exists to catch, and the driver returns `ok` while the
    host turns it into `FAILED_PERMANENT(EMPTY_RESULT)` rather than caching a parse of nothing.

    A `.ppt` with CONTENT is not written here. PowerPoint 97's record tree -- `UserEditAtom`, the
    persist-pointer blocks, `DocumentContainer`, `SlideListWithText` -- is a graph of offsets into
    itself, and hand-assembling one would be a second implementation of a format whose reader is
    the thing under test. `deck.pptx` and `deck.odp` carry the presentation cases.
    """
    return compound_file("PowerPoint Document", b"")


def doc_memo() -> bytes:
    """A compound file with a `WordDocument` stream carrying no valid FIB.

    Detected as `doc` and REFUSED as `CORRUPT_INPUT` ("invalid FIB magic"), which makes it the
    negative half of the `.doc` row: the driver recognises the format and declines the bytes,
    which are two different answers and the suite checks both.

    A `.doc` with content is not written here for the same reason `deck.ppt` has none -- the Word
    97 FIB indexes a piece table in a second stream -- and the consequence is stated in the
    fixtures README rather than left to a reader to notice: there is no positive `.doc` case in
    this corpus, and the `capability` suite's per-document assertions never run on one.
    """
    return compound_file("WordDocument", b"omniweave office fixture: not a Word 97 FIB")


FIXTURES: dict[str, tuple[object, str | None, str]] = {
    "rich.docx": (
        docx_rich,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "every non-trivial capability row at once: two heading levels, styled runs, a hyperlink, "
        "a bookmark, a merged-cell table, displayed and inline OMML, an embedded PNG, a footnote",
    ),
    "deepxml.docx": (
        docx_deep,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "400 nested elements past anydoc's compiled-in max_xml_depth = 256, so the one limit that "
        "lives in someone else's crate becomes observable from Python",
    ),
    "sheet.xlsx": (
        xlsx_sheet,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "a merged cell, so the grid carries a `covered` slot pointing back at its origin",
    ),
    "deck.pptx": (
        pptx_deck,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "a speaker note, which anydoc emits as Block::BlockQuote -- indistinguishable from a real "
        "quotation, so Kind.SPEAKER_NOTE has no producer on this path and a test says so",
    ),
    "notes.odt": (
        odt_text,
        "application/vnd.oasis.opendocument.text",
        "the ODF text body: a heading with an outline level, a paragraph, and a list",
    ),
    "sheet.ods": (
        ods_sheet,
        "application/vnd.oasis.opendocument.spreadsheet",
        "the ODF spreadsheet's own span spelling, table:number-columns-spanned plus an explicit "
        "covered-table-cell, which is a different encoding of the same exactly-once grid",
    ),
    "deck.odp": (
        odp_deck,
        "application/vnd.oasis.opendocument.presentation",
        "the ODF presentation body, where slide text arrives through draw:frame text boxes",
    ),
    "encrypted.odt": (
        odt_encrypted,
        "application/vnd.oasis.opendocument.text",
        "an ODF manifest declaring encryption-data. FailureClass.ENCRYPTED, decided from the "
        "manifest BEFORE any attempt to decode the content",
    ),
    "book.epub": (
        epub_book,
        "application/epub+zip",
        "the four Block variants the office formats above do not reach: rule, code_block, "
        "block_quote and an anchor-kind link target",
    ),
    "memo.rtf": (
        rtf_memo,
        "application/rtf",
        "the one non-container text format anydoc serves; no ZIP, no CFB, no XML",
    ),
    "rows.csv": (
        csv_rows,
        "text/csv",
        "the format with NO signature. It decodes only because the sidecar names its media type, "
        "which is the whole reason UnitRef carries one",
    ),
    "truncated.docx": (
        truncated_docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "rich.docx cut in half: the central directory is gone, so MalformedError -> CORRUPT_INPUT",
    ),
    "sheet.xls": (
        xls_sheet,
        "application/vnd.ms-excel",
        "a real BIFF8 workbook in a compound file. anydoc's own name for this format is `xlsx` -- "
        "a parser family, not a media type -- so the card's `xls` token and the decoder's name "
        "differ here and nowhere else",
    ),
    "deck.ppt": (
        ppt_deck,
        "application/vnd.ms-powerpoint",
        "a valid but EMPTY PowerPoint 97 stream: the driver returns ok with zero blocks and "
        "is_valid_nonempty() is what turns that into FAILED_PERMANENT(EMPTY_RESULT) host-side",
    ),
    "memo.doc": (
        doc_memo,
        "application/msword",
        "a WordDocument stream with no valid FIB: recognised as `doc` by sniff() and refused as "
        "CORRUPT_INPUT by parse(), which are two different answers and both are checked",
    ),
    "not_a_document.bin": (
        not_a_document,
        None,
        "an ELF header. sniff() returns (), a legitimate `not mine`, and parse() refuses with "
        "UNSUPPORTED_FORMAT. NO SIDECAR MEDIA TYPE, because nothing routed it",
    ),
}


SIDECAR = """# {name}.meta.toml -- 13-quality.md section 4.4's fixture manifest.
#
# {purpose}
[fixture]
sha256 = "{digest}"
bytes = {size}
{media}provenance = "generated"
spdx = "Apache-2.0"
generator = "fixtures/gen/gen_office_fixtures.py"
# `generated` is 13-quality.md section 4.2's PREFERRED provenance and requires two things: the
# generator path under fixtures/gen/ and the expected output sha256. Both are above. It also
# carries no `review_by`: the review window is "none for `generated` and `authored`, which have no
# external dependency to rot", and this file depends on nothing outside this repository.
"""


def sidecar(name: str, data: bytes, media_type: str | None, purpose: str) -> str:
    """One `.meta.toml` per fixture. `media_type` is omitted, not empty, when nothing routed it.

    An absent key and `media_type = ""` are different claims: the first says no host would have
    decided a type for these bytes, the second would say a host decided on the empty string. The
    kit reads the key's absence as `UnitRef.media_type = None`, which is what a real host passes
    for a file it could not route.
    """
    media = f'media_type = "{media_type}"\n' if media_type else ""
    return SIDECAR.format(
        name=name,
        purpose=purpose,
        digest=hashlib.sha256(data).hexdigest(),
        size=len(data),
        media=media,
    )


def report(line: str) -> None:
    """`print` is banned by ruff's T20 across this repository, so the report goes to stdout
    directly -- the same route `fixtures/gen/gen_5000p_pdf.py` takes for the same reason."""
    sys.stdout.write(f"{line}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, (build, media_type, purpose) in sorted(FIXTURES.items()):
        data = build()  # type: ignore[operator]
        (args.out / name).write_bytes(data)
        (args.out / f"{name}.meta.toml").write_text(
            sidecar(name, data, media_type, purpose), encoding="utf-8", newline="\n"
        )
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        report(f"{name:22s} {len(data):7d} bytes")
    (args.out / "EXPECTED.sha256").write_text("".join(lines), encoding="utf-8", newline="\n")
    report(f"\n{len(lines)} fixtures -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
